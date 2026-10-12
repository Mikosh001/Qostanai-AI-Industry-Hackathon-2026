"""Server-issued exam grants and revocable device credentials (protocol 2).

Moodle's Ed25519 private key never travels to an agent. A device credential
authenticates transport, not camera/OS attestation or the honesty of a local admin.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import HTTPException
from .security import canonical


def unb64(value):
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def verify_grant(token, public_key, *, expired=False):
    try:
        if not isinstance(token, str) or len(token) > 16000:
            raise ValueError("Invalid launch size")
        version, raw, signature = token.split(".")
        if version != "SG2":
            raise ValueError("An Ed25519 launch is required; legacy HMAC launches are disabled")
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key)).verify(unb64(signature), raw.encode())
        value = json.loads(unb64(raw), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite claim")))
        if not isinstance(value, dict) or value.get("aud") != "sergek-exam-v2":
            raise ValueError("Invalid launch audience")
        for name in ("nonce", "userid", "quizid", "url"):
            if not isinstance(value.get(name), str) or not value[name] or len(value[name]) > 2048:
                raise ValueError("Invalid launch claim: " + name)
        if not __import__('re').fullmatch(r'[0-9a-f]{32}',value.get('device_id','')):
            raise ValueError('Launch must name an enrolled device')
        for name in ("iat", "exp"):
            if isinstance(value.get(name), bool) or not isinstance(value.get(name), (int, float)):
                raise ValueError("Invalid launch time")
        if not 0 < value["exp"] - value["iat"] <= 1800 or value["iat"] > time.time() + 30:
            raise ValueError("Invalid launch lifetime")
        if not expired and value["exp"] < time.time():
            raise ValueError("Expired launch")
        if value.get("mode") not in ("strict", "monitor"):
            raise ValueError("Invalid launch mode")
        return value
    except Exception as exc:
        raise ValueError("Invalid Moodle launch: " + str(exc)) from exc


def initialize(store):
    if getattr(store, "_trust_initialized", False):
        return
    with store.lock:
        if getattr(store, '_trust_initialized', False):return
        store.db.executescript("""
        CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY,name TEXT NOT NULL,revoked INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS issued_grants(nonce TEXT PRIMARY KEY,token_hash TEXT NOT NULL,claims TEXT NOT NULL,device_id TEXT,session_id TEXT,attempt_id TEXT);
        CREATE INDEX IF NOT EXISTS grant_session ON issued_grants(session_id);
        """)
        store.db.commit()
        store._trust_initialized = True


def enroll(store, name):
    initialize(store)
    did, key = uuid.uuid4().hex, secrets.token_urlsafe(48)
    with store.lock:
        store.db.execute("INSERT INTO devices VALUES(?,?,0,?)", (did, str(name)[:120], time.time()))
        store.db.commit()
    store.set_secret("device:" + did, key)
    store.audit("device_enrolled", {"device_id": did, "name": str(name)[:120]})
    return {"device_id": did, "device_key": key}


def authenticate(store, did, signature, raw):
    initialize(store)
    with store.lock:
        device = store.db.execute("SELECT revoked FROM devices WHERE id=?", (did,)).fetchone()
    if not device or device[0]:
        raise HTTPException(403, "Unknown or revoked device")
    key = store.secret("device:" + did, "")
    if not key or not __import__('re').fullmatch(r'[0-9a-f]{64}',signature) or not hmac.compare_digest(signature, hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()):
        raise HTTPException(403, "Invalid device signature")
    return did


def issue(store, token):
    initialize(store)
    value = verify_grant(token, store.setting("moodle_public_key", ""))
    if not device_live(store,value['device_id']):
        raise ValueError('Launch names an unknown or revoked device')
    digest = hashlib.sha256(token.encode()).hexdigest()
    with store.lock:
        row = store.db.execute("SELECT token_hash FROM issued_grants WHERE nonce=?", (value["nonce"],)).fetchone()
        if row and row[0] != digest:
            raise HTTPException(409, "Nonce already issued for different claims")
        store.db.execute("INSERT OR IGNORE INTO issued_grants(nonce,token_hash,claims) VALUES(?,?,?)", (value["nonce"], digest, json.dumps(value)))
        store.db.commit()
    return value


def bind(store, item, did, token):
    """Must run in the ingest transaction; a rejected packet cannot consume a grant."""
    value = verify_grant(token, store.setting("moodle_public_key", ""), expired=True)
    if value['device_id']!=did:
        raise HTTPException(403,'Launch was issued to another device')
    row = store.db.execute("SELECT * FROM issued_grants WHERE nonce=?", (value["nonce"],)).fetchone()
    if not did or not row or row["token_hash"] != hashlib.sha256(token.encode()).hexdigest():
        raise HTTPException(403, "A server-issued launch and enrolled device are required")
    if row["session_id"] and (row["session_id"] != item["id"] or row["device_id"] != did):
        raise HTTPException(409, "Launch already bound to another device or session")
    if not row["session_id"] and value["exp"] < time.time():
        raise HTTPException(403, "Expired unbound launch")
    claims = item["data"].get("moodle", {})
    if any(claims.get(k) != value[k] for k in ("nonce", "userid", "quizid")) or item["data"].get("mode") != value["mode"] or item["data"].get("exam_url") != value["url"]:
        raise HTTPException(403, "Session does not match issued launch")
    if item["data"].get("platform") != "moodle":
        raise HTTPException(403, "Launch platform mismatch")
    store.db.execute("UPDATE issued_grants SET device_id=?,session_id=? WHERE nonce=?", (did, item["id"], value["nonce"]))
    item["data"]["device_id"] = did


def device_live(store, did):
    if not did:
        return False
    with store.lock:
        row = store.db.execute("SELECT revoked FROM devices WHERE id=?", (did,)).fetchone()
    return bool(row and not row[0])
