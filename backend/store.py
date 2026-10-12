import sqlite3, json, threading, uuid, hashlib, time
from datetime import datetime, timezone
from .security import canonical, encrypt, decrypt, load_key


def utc():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = path
        self._secret_cache = {}
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,created TEXT NOT NULL,ended TEXT,status TEXT NOT NULL,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,created TEXT NOT NULL,kind TEXT NOT NULL,detail TEXT NOT NULL,previous_hash TEXT NOT NULL,hash TEXT NOT NULL,media TEXT,verdict TEXT NOT NULL DEFAULT 'pending',note TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS event_session ON events(session_id,created);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,created TEXT NOT NULL,action TEXT NOT NULL,detail TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS launches(nonce TEXT PRIMARY KEY,session_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS answers(session_id TEXT NOT NULL,question_id TEXT NOT NULL,answer TEXT NOT NULL,PRIMARY KEY(session_id,question_id));
        CREATE TABLE IF NOT EXISTS remote_sessions(id TEXT PRIMARY KEY,data TEXT NOT NULL,updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS received_packets(id TEXT PRIMARY KEY,received REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS integrity_anchors(session_id TEXT PRIMARY KEY,count INTEGER NOT NULL,head TEXT NOT NULL);
        """)
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(sessions)')}
        if 'started' not in columns:
            self.db.execute('ALTER TABLE sessions ADD COLUMN started TEXT')
            self.db.execute("UPDATE sessions SET started=json_extract(data,'$.active_started_at')")
        self.db.execute("CREATE INDEX IF NOT EXISTS session_nonce ON sessions(json_extract(data,'$.moodle.nonce'))")
        self.db.execute('CREATE INDEX IF NOT EXISTS packet_received ON received_packets(received)')
        for row in self.db.execute('SELECT id,data FROM sessions WHERE id NOT IN (SELECT session_id FROM integrity_anchors)').fetchall():
            events=self.db.execute('SELECT hash FROM events WHERE session_id=? ORDER BY rowid',(row['id'],)).fetchall()
            data=json.loads(row['data']);data['integrity_legacy']=True
            self.db.execute('UPDATE sessions SET data=? WHERE id=?',(json.dumps(data,ensure_ascii=False),row['id']))
            self.update_anchor(row['id'],len(events),events[-1][0] if events else '0'*64)
        self.db.commit()

    def set_secret(self, key, value):
        """Encrypt transport credentials at rest; DPAPI protects the wrapping key on Windows."""
        import base64
        with self.lock:
            wrapping = load_key(self.path.parent / "credentials.key")
            encoded=base64.b64encode(encrypt(canonical(value), wrapping)).decode()
            self.set_setting("secret:" + key, encoded)
            self._secret_cache[key]=(encoded,value)
            self.db.execute("DELETE FROM settings WHERE key=?", (key,))
            self.db.commit()

    def secret(self, key, default=None):
        import base64
        encoded = self.setting("secret:" + key)
        if encoded:
            with self.lock:
                cached=self._secret_cache.get(key)
                if cached and cached[0]==encoded:return cached[1]
                wrapping = load_key(self.path.parent / "credentials.key")
                result=json.loads(decrypt(base64.b64decode(encoded), wrapping))
                self._secret_cache[key]=(encoded,result)
                return result
        legacy = self.setting(key)
        if legacy is not None:
            self.set_secret(key, legacy)
            return legacy
        return default

    def anchor(self, sid):
        with self.lock:
            row = self.db.execute("SELECT count,head FROM integrity_anchors WHERE session_id=?", (sid,)).fetchone()
        return dict(row) if row else None

    def update_anchor(self, sid, count, head):
        # The caller commits this together with the event write.
        self.db.execute("INSERT OR REPLACE INTO integrity_anchors VALUES(?,?,?)", (sid, count, head))

    def setting(self, key, default=None):
        with self.lock:
            row = self.db.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.lock:
            self.db.execute(
                "INSERT OR REPLACE INTO settings VALUES(?,?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )
            self.db.commit()

    def audit(self, action, detail):
        with self.lock:
            self.db.execute(
                "INSERT INTO audit(created,action,detail) VALUES(?,?,?)",
                (utc(), action, json.dumps(detail, ensure_ascii=False)),
            )
            self.db.commit()

    def create_session(self, data, nonce=""):
        sid = uuid.uuid4().hex
        with self.lock:
            try:
                if nonce:
                    self.db.execute("INSERT INTO launches VALUES(?,?)", (nonce, sid))
                self.db.execute(
                    "INSERT INTO sessions(id,created,ended,status,data) VALUES(?,?,NULL,?,?)",
                    (sid, utc(), "preflight", json.dumps(data, ensure_ascii=False)),
                )
                self.update_anchor(sid, 0, "0" * 64)
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return self.session(sid)

    def session(self, sid):
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM sessions WHERE id=?", (sid,)
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["data"] = json.loads(result["data"])
        return result

    def sessions(self,limit=None,offset=0,query=''):
        with self.lock:
            sql='SELECT * FROM sessions'
            args=[]
            if query:
                sql+=" WHERE (coalesce(json_extract(data,'$.student'),'') || ' ' || coalesce(json_extract(data,'$.exam'),'')) LIKE ? ESCAPE '\\'"
                args.append('%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
            sql+=' ORDER BY created DESC,id DESC'
            if limit is not None:sql+=' LIMIT ? OFFSET ?';args.extend([limit,offset])
            rows=self.db.execute(sql,args).fetchall()
        return [{**dict(r), 'data': json.loads(r['data'])} for r in rows]

    def event_counts(self,sids):
        from .event_policy import review_category
        counts={sid:{'event_count':0,'journal_count':0} for sid in sids}
        if not sids:return counts
        with self.lock:
            rows=self.db.execute('SELECT session_id,kind,detail FROM events WHERE session_id IN ('+','.join('?' for _ in sids)+')',sids).fetchall()
        for row in rows:
            value=counts[row['session_id']];value['journal_count']+=1
            value['event_count']+=review_category(row['kind'],json.loads(row['detail']))!='technical'
        return counts

    def session_by_nonce(self, nonce):
        with self.lock:
            row = self.db.execute("SELECT * FROM sessions WHERE json_extract(data,'$.moodle.nonce')=? ORDER BY created DESC LIMIT 1", (nonce,)).fetchone()
        return {**dict(row), 'data': json.loads(row['data'])} if row else None

    def update_session(self, sid, status=None, patch=None):
        with self.lock:
            item = self.session(sid)
            if not item:
                raise KeyError(sid)
            item["data"].update(patch or {})
            status = status or item["status"]
            if item['status'] in ('completed', 'interrupted') and status not in ('completed', 'interrupted'):
                raise ValueError('A finished session cannot be restarted')
            started = item.get('started') or (item['data'].get('active_started_at') if status == 'active' else None)
            if status == 'active' and not started:
                started = utc()
            if started:
                item['data']['active_started_at'] = started
            ended = (item['ended'] or utc()) if status in ("completed", "interrupted") else item["ended"]
            if ended:
                item['data']['finished_at'] = ended
            self.db.execute(
                "UPDATE sessions SET status=?,started=?,ended=?,data=? WHERE id=?",
                (status, started, ended, json.dumps(item["data"], ensure_ascii=False), sid),
            )
            self.db.commit()
        return self.session(sid)

    def add_event(self, sid, kind, detail):
        with self.lock:
            if not self.session(sid):
                raise KeyError(sid)
            eid = uuid.uuid4().hex
            created = utc()
            row = self.db.execute(
                "SELECT hash FROM events WHERE session_id=? ORDER BY rowid DESC LIMIT 1",
                (sid,),
            ).fetchone()
            previous = row[0] if row else "0" * 64
            count=self.db.execute('SELECT count(*) FROM events WHERE session_id=?',(sid,)).fetchone()[0]
            if self.anchor(sid)!={'count':count,'head':previous}:
                raise ValueError('Existing event history does not match its completeness anchor')
            digest = hashlib.sha256(
                canonical(
                    {
                        "id": eid,
                        "session_id": sid,
                        "created": created,
                        "kind": kind,
                        "detail": detail,
                        "previous_hash": previous,
                    }
                )
            ).hexdigest()
            self.db.execute(
                "INSERT INTO events(id,session_id,created,kind,detail,previous_hash,hash) VALUES(?,?,?,?,?,?,?)",
                (
                    eid,
                    sid,
                    created,
                    kind,
                    json.dumps(detail, ensure_ascii=False),
                    previous,
                    digest,
                ),
            )
            self.update_anchor(sid, count+1, digest)
            self.db.commit()
        return self.event(eid)

    def event(self, eid):
        with self.lock:
            row = self.db.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["detail"] = json.loads(result["detail"])
        return result

    def events(self, sid):
        with self.lock:
            rows = self.db.execute('SELECT * FROM events WHERE session_id=? ORDER BY rowid', (sid,)).fetchall()
        return [{**dict(r), 'detail': json.loads(r['detail'])} for r in rows]

    def attach_media(self, eid, path, digest=None, size=None):
        with self.lock:
            try:
                event=self.event(eid)
                if not event:raise KeyError(eid)
                self.db.execute("UPDATE events SET media=? WHERE id=?", (path, eid))
                if digest:
                    self.add_event(event['session_id'],'evidence_committed',{'event_id':eid,'sha256':digest,'bytes':size})
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    def review(self, eid, verdict, note):
        with self.lock:
            self.db.execute(
                "UPDATE events SET verdict=?,note=? WHERE id=?", (verdict, note, eid)
            )
            self.db.commit()
            self.audit(
                "event_review", {"event_id": eid, "verdict": verdict, "note": note}
            )
        return self.event(eid)

    def integrity(self, sid):
        item=self.session(sid)
        if not item or item['data'].get('integrity_legacy'):return False
        previous = "0" * 64
        events = self.events(sid)
        for event in events:
            expected = hashlib.sha256(
                canonical(
                    {
                        k: event[k]
                        for k in [
                            "id",
                            "session_id",
                            "created",
                            "kind",
                            "detail",
                            "previous_hash",
                        ]
                    }
                )
            ).hexdigest()
            if event["previous_hash"] != previous or event["hash"] != expected:
                return False
            previous = event["hash"]
        anchor = self.anchor(sid)
        if anchor is None:
            # Legacy data has no independent completeness anchor.
            return False
        receipt = self.setting("hub_anchor:" + sid)
        if receipt and (receipt["count"] > len(events) or
                        (receipt["count"] and events[receipt["count"]-1]["hash"] != receipt["head"])):
            return False
        return anchor == {"count": len(events), "head": previous}

    def save_answer(self, sid, qid, answer):
        with self.lock:
            self.db.execute(
                "INSERT OR REPLACE INTO answers VALUES(?,?,?)",
                (sid, qid, json.dumps(answer)),
            )
            self.db.commit()

    def answers(self, sid):
        with self.lock:
            return {
                r[0]: json.loads(r[1])
                for r in self.db.execute(
                    "SELECT question_id,answer FROM answers WHERE session_id=?", (sid,)
                )
            }

    def delete_session(self, sid):
        with self.lock:
            for table in ["events", "answers", "integrity_anchors"]:
                self.db.execute(f"DELETE FROM {table} WHERE session_id=?", (sid,))
            # Keep the opaque single-use nonce consumed after deleting its session.
            self.db.execute("DELETE FROM sessions WHERE id=?", (sid,))
            self.db.commit()
            self.audit("session_deleted", {"session_id": sid})
