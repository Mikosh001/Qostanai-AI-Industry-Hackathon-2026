import hashlib, hmac, secrets, json, base64, os, time, math, tempfile
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
    # Atomically publish a complete file. Concurrent first requests must never
    # create different keys or read a half-written credential wrapping key.
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.key-',delete=False) as stream:
        temporary=Path(stream.name)
        stream.write(blob);stream.flush();os.fsync(stream.fileno())
    try:
        if os.name!='nt':os.chmod(temporary,0o600)
        try:os.link(temporary,path)
        except FileExistsError:return load_key(path)
        return key
    finally:
        temporary.unlink(missing_ok=True)


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
    if not isinstance(value, dict):
        raise ValueError("Invalid launch payload")
    expiry = value.get("exp")
    if isinstance(expiry, bool) or not isinstance(expiry, (float, int)) or not 0 < expiry < 1e12 or not math.isfinite(expiry) or expiry < time.time():
        raise ValueError("Expired launch")
    for field in ("nonce", "userid", "quizid", "url"):
        claim = value.get(field)
        if isinstance(claim, bool) or not isinstance(claim, (str, int)) or not claim:
            raise ValueError("Incomplete launch")
    if not isinstance(value["nonce"], str) or not isinstance(value["url"], str):
        raise ValueError("Invalid launch claims")
    return value
