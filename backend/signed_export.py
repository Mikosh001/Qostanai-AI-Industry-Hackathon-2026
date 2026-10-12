"""Portable signed JSON. Trust the public key through the university operator."""
import base64
import hashlib
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey,Ed25519PublicKey
from .security import load_key,canonical


def public_key(store):
    private=Ed25519PrivateKey.from_private_bytes(load_key(store.path.parent/'report-signing.key'))
    return private.public_key().public_bytes_raw().hex()


def sign_report(store,payload):
    private=Ed25519PrivateKey.from_private_bytes(load_key(store.path.parent/'report-signing.key'))
    public=private.public_key().public_bytes_raw().hex()
    return {'format':'sergek-signed-report/1','algorithm':'Ed25519','public_key':public,
            'key_id':hashlib.sha256(bytes.fromhex(public)).hexdigest(),
            'payload':payload,'signature':base64.b64encode(private.sign(canonical(payload))).decode()}


def verify_report(value, trusted_public_key):
    if value.get('algorithm')!='Ed25519' or value.get('format')!='sergek-signed-report/1' or value.get('public_key')!=trusted_public_key:
        raise ValueError('The report is not signed by the trusted university key')
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(trusted_public_key)).verify(base64.b64decode(value['signature'],validate=True),canonical(value['payload']))
    return value['payload']
