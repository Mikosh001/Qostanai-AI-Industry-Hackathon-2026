import sqlite3, json, threading, uuid, hashlib, time
from datetime import datetime, timezone
from .security import canonical


def utc():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
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
        """)
        self.db.commit()
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(sessions)')}
        if 'started' not in columns:
            self.db.execute('ALTER TABLE sessions ADD COLUMN started TEXT')
            self.db.execute("UPDATE sessions SET started=json_extract(data,'$.active_started_at')")
        self.db.execute("CREATE INDEX IF NOT EXISTS session_nonce ON sessions(json_extract(data,'$.moodle.nonce'))")
        self.db.execute('CREATE INDEX IF NOT EXISTS packet_received ON received_packets(received)')
        self.db.commit()

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

    def sessions(self):
        with self.lock:
            rows = self.db.execute('SELECT * FROM sessions ORDER BY created DESC').fetchall()
        return [{**dict(r), 'data': json.loads(r['data'])} for r in rows]

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

    def attach_media(self, eid, path):
        with self.lock:
            self.db.execute("UPDATE events SET media=? WHERE id=?", (path, eid))
            self.db.commit()

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
        previous = "0" * 64
        for event in self.events(sid):
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
        return True

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
            for table in ["events", "answers"]:
                self.db.execute(f"DELETE FROM {table} WHERE session_id=?", (sid,))
            # Keep the opaque single-use nonce consumed after deleting its session.
            self.db.execute("DELETE FROM sessions WHERE id=?", (sid,))
            self.db.commit()
            self.audit("session_deleted", {"session_id": sid})
