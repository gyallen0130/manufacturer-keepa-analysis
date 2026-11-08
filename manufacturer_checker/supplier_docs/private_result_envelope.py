"""Recipient-only encryption of private, normalized supplier inspection results.

The trusted PRIVATE runner uses an independently pinned X25519 public key. The
corresponding private key MUST stay on the owner's trusted local computer and
must NEVER enter GitHub Actions, GitHub Secrets, Colab, or this source repo.

Only one in-memory inspection response is encrypted. No files, network, raw
Google credentials, extra cloud services, or logging. The encrypted envelope
can later be downloaded by an authorized user from a PRIVATE short-retention
artifact, but GitHub artifact access alone MUST NOT grant decryption.

This is an application-layer envelope, not an authenticated identity or
guarantee that supplier files/owner keys are safe. Confidentiality depends on
the pin being independently verified and the private key remaining secret.
"""
import base64
import binascii
import hashlib
import hmac
import json
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VERSION = 'supplier-private-result-envelope-v1'
CONTEXT = b'supplier-private-results/v1/read-only'
MAX_PLAINTEXT_BYTES = 1_500_000
MAX_ENVELOPE_BYTES = 2_300_000
HEX_SHA256 = re.compile(r'^[0-9a-f]{64}$')
_B64 = re.compile(r'^[A-Za-z0-9+/]+={0,2}$')
_FIELDS = frozenset({
    'schema_version', 'recipient_fingerprint_sha256',
    'ephemeral_public_key_b64', 'salt_b64', 'nonce_b64',
    'ciphertext_b64',
})


def _encode(raw):
    return base64.b64encode(raw).decode('ascii')


def _decode(value, *, size):
    if (not isinstance(value, str) or not _B64.fullmatch(value)
            or len(value) > ((size + 2) // 3) * 4 + 4):
        raise ValueError('invalid public-key or encrypted result format')
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError('invalid public-key or encrypted result encoding') from None
    if len(decoded) != size:
        raise ValueError('unexpected public-key or envelope field size')
    return decoded


def _recipient_fingerprint(public_bytes):
    return hashlib.sha256(public_bytes).hexdigest()


def _key(shared, salt):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
                info=CONTEXT).derive(shared)


def _aad(header):
    return json.dumps(header, ensure_ascii=True, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def recipient_public_key_b64(private_key):
    """For a trusted local key: public key only, not a backup of the secret."""
    if not isinstance(private_key, X25519PrivateKey):
        raise ValueError('local X25519 private key required')
    return _encode(private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def seal_private_inspections(
        report, *, recipient_public_key_b64, trusted_fingerprint_sha256):
    """Seal exact in-memory read result to the independently pinned owner key.

    The caller may store ONLY the encrypted envelope, not report or its raw
    JSON bytes. Fail closed on unrecognized input, invalid pin and size.
    """
    if (not isinstance(trusted_fingerprint_sha256, str)
            or not HEX_SHA256.fullmatch(trusted_fingerprint_sha256)):
        raise ValueError('independently verified recipient fingerprint required')
    public_bytes = _decode(recipient_public_key_b64, size=32)
    actual = _recipient_fingerprint(public_bytes)
    if not hmac.compare_digest(actual, trusted_fingerprint_sha256):
        raise ValueError('recipient public key does not match trusted fingerprint')
    if (not isinstance(report, dict)
            or set(report) != {'public_summary', 'private_inspections'}
            or not isinstance(report['public_summary'], dict)
            or not isinstance(report['private_inspections'], list)):
        raise ValueError('incomplete private supplier inspection result')
    raw = json.dumps(report, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':'), allow_nan=False).encode('utf-8')
    if not 1 <= len(raw) <= MAX_PLAINTEXT_BYTES:
        raise ValueError('private supplier inspection payload too large')
    recipient = X25519PublicKey.from_public_bytes(public_bytes)
    ephemeral = X25519PrivateKey.generate()
    ephemeral_public = ephemeral.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    # Cryptographically independent random salt and nonce per envelope.
    from os import urandom
    salt, nonce = urandom(16), urandom(12)
    header = {
        'schema_version': VERSION,
        'recipient_fingerprint_sha256': actual,
        'ephemeral_public_key_b64': _encode(ephemeral_public),
        'salt_b64': _encode(salt),
        'nonce_b64': _encode(nonce),
    }
    encrypted = AESGCM(_key(ephemeral.exchange(recipient), salt)).encrypt(
        nonce, raw, _aad(header))
    envelope = {**header, 'ciphertext_b64': _encode(encrypted)}
    if len(_aad(envelope)) > MAX_ENVELOPE_BYTES:
        raise ValueError('private encrypted envelope exceeds size limit')
    return envelope


def open_private_inspections(envelope, *, recipient_private_key,
                             trusted_fingerprint_sha256):
    """Local ONLY; require the actual owner private key to decrypt.

    Does not authenticate source Google data, reviewer identity or purchase
    decisions. Never write decrypted plaintext to public logs or GitHub.
    """
    if not isinstance(recipient_private_key, X25519PrivateKey):
        raise ValueError('local private key required')
    if (not isinstance(trusted_fingerprint_sha256, str)
            or not HEX_SHA256.fullmatch(trusted_fingerprint_sha256)
            or not isinstance(envelope, dict)
            or set(envelope) != _FIELDS
            or len(_aad(envelope)) > MAX_ENVELOPE_BYTES):
        raise ValueError('invalid encrypted inspection envelope')
    own_public_b64 = recipient_public_key_b64(recipient_private_key)
    own_fingerprint = _recipient_fingerprint(_decode(own_public_b64, size=32))
    if (not hmac.compare_digest(own_fingerprint, trusted_fingerprint_sha256)
            or not hmac.compare_digest(
                envelope['recipient_fingerprint_sha256'],
                trusted_fingerprint_sha256)
            or envelope['schema_version'] != VERSION):
        raise ValueError('encrypted inspection recipient is not trusted')
    ephemeral_public = X25519PublicKey.from_public_bytes(
        _decode(envelope['ephemeral_public_key_b64'], size=32))
    salt = _decode(envelope['salt_b64'], size=16)
    nonce = _decode(envelope['nonce_b64'], size=12)
    ciphertext_encoded = envelope['ciphertext_b64']
    if (not isinstance(ciphertext_encoded, str)
            or not _B64.fullmatch(ciphertext_encoded)
            or len(ciphertext_encoded) > ((MAX_PLAINTEXT_BYTES + 16 + 2) // 3) * 4 + 4):
        raise ValueError('invalid private encrypted payload')
    try:
        ciphertext = base64.b64decode(ciphertext_encoded, validate=True)
        if not 16 <= len(ciphertext) <= MAX_PLAINTEXT_BYTES + 16:
            raise ValueError('oversized encrypted supplier result')
        header = {k: envelope[k] for k in _FIELDS if k != 'ciphertext_b64'}
        raw = AESGCM(
            _key(recipient_private_key.exchange(ephemeral_public), salt)
        ).decrypt(nonce, ciphertext, _aad(header))
        result = json.loads(raw)
    except (binascii.Error, ValueError, InvalidTag, UnicodeDecodeError,
            json.JSONDecodeError):
        raise ValueError('private supplier result could not be verified') from None
    if (not isinstance(result, dict)
            or set(result) != {'public_summary', 'private_inspections'}
            or not isinstance(result['public_summary'], dict)
            or not isinstance(result['private_inspections'], list)):
        raise ValueError('decrypted supplier result does not match schema')
    return result
