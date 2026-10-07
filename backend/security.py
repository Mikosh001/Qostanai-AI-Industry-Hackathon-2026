import hashlib, hmac, secrets, json, base64, os, time
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    value = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ":" + value.hex()


def verify_password(password: str, encoded: str) -> bool:
    try:
        salt, value = encoded.split(":")
        actual = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
        )
        return hmac.compare_digest(actual.hex(), value)
    except (ValueError, TypeError):
        return False


def canonical(value) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def load_key(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        blob = path.read_bytes()
        if blob.startswith(b"DPAPI:"):
            import win32crypt

            return win32crypt.CryptUnprotectData(blob[6:], None, None, None, 0)[1]
        return blob
    key = AESGCM.generate_key(bit_length=256)
    if os.name == "nt":
        import win32crypt

        blob = b"DPAPI:" + win32crypt.CryptProtectData(
            key, "Sergek media", None, None, None, 0
        )
    else:
        blob = key
    path.write_bytes(blob)
    if os.name != "nt":
        os.chmod(path, 0o600)
    return key


def encrypt(blob: bytes, key: bytes) -> bytes:
    nonce = secrets.token_bytes(12)
    return b"SG1" + nonce + AESGCM(key).encrypt(nonce, blob, b"Sergek evidence v1")


def decrypt(blob: bytes, key: bytes) -> bytes:
    if blob[:3] != b"SG1":
        raise ValueError("Invalid evidence format")
    return AESGCM(key).decrypt(blob[3:15], blob[15:], b"Sergek evidence v1")


def sign_launch(payload: dict, key: str) -> str:
    raw = base64.urlsafe_b64encode(canonical(payload)).decode().rstrip("=")
    return raw + "." + hmac.new(key.encode(), raw.encode(), hashlib.sha256).hexdigest()


def verify_launch(token: str, key: str) -> dict:
    raw, signature = token.split(".", 1)
    expected = hmac.new(key.encode(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid launch signature")
    value = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    if not isinstance(value.get("exp"), (float, int)) or value["exp"] < time.time():
        raise ValueError("Expired launch")
    for field in ("nonce", "userid", "quizid", "url"):
        if not value.get(field):
            raise ValueError("Incomplete launch")
    return value
