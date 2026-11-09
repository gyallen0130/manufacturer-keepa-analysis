"""Independent offline recovery copy of a signed, encrypted supplier audit.

Pure bytes-only operations: no GitHub API, Drive, disk writes, secrets API,
console output, billing changes, key creation or automatic restoration.

Create the recovery archive with a dedicated high-entropy recovery Fernet key
on a trusted machine, then store archive and recovery key in DIFFERENT secure
locations outside GitHub. The worker's primary Fernet key is never embedded in
the archive. The review-signing PRIVATE key is never needed.

An offline restoration produces a fresh encrypted checkpoint only; NEVER
automatically PUT it to GitHub, since the remote may have newer revisions.
"""
import hashlib
import hmac
import json
import re

from cryptography.fernet import InvalidToken
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .private_audit_bundle import (
    MAX_PLAINTEXT_BYTES, verify_audit_bundle,
)
from .review_gate import _canonical
from .snapshot_store import _cipher, MAX_CIPHERTEXT_BYTES

SCHEMA = 'supplier-offline-recovery-archive-v1'
_BLOB_SHA = re.compile(r'^[0-9a-f]{40}$')
MAX_RECOVERY_ARCHIVE_BYTES = 6_500_000


def _trusted_keyring_digest(public_keys):
    if not isinstance(public_keys, dict) or not public_keys:
        raise ValueError('trusted public-key ring required')
    members = {}
    for reviewer, pub in public_keys.items():
        if (not isinstance(reviewer, str) or not reviewer
                or not isinstance(pub, Ed25519PublicKey)):
            raise ValueError('invalid recovery public-key ring')
        members[reviewer] = pub.public_bytes(
            Encoding.Raw, PublicFormat.Raw).hex()
    return hashlib.sha256(_canonical(members)).hexdigest()


def _github_blob_sha(data):
    if not isinstance(data, bytes):
        raise ValueError('encrypted checkpoint must be bytes')
    return hashlib.sha1(
        b'blob ' + str(len(data)).encode() + b'\0' + data
    ).hexdigest()


def _check_distinct_keys(a, b):
    if (not isinstance(a, bytes) or not isinstance(b, bytes)
            or hmac.compare_digest(a, b)):
        raise ValueError('primary and recovery keys must be independent')
    _cipher(a)
    _cipher(b)


def create_offline_recovery_archive(
        encrypted_checkpoint, *, primary_key, recovery_key,
        source_blob_sha, trusted_public_keys):
    """Re-encrypt a fully verified audit using a DIFFERENT recovery key.

    Caller must independently confirm source_blob_sha is the most recently
    read private checkpoint SHA and securely back up recovery_key separately.
    """
    _check_distinct_keys(primary_key, recovery_key)
    if (not isinstance(source_blob_sha, str)
            or not _BLOB_SHA.fullmatch(source_blob_sha)
            or not isinstance(encrypted_checkpoint, bytes)
            or not 1 <= len(encrypted_checkpoint) <= MAX_CIPHERTEXT_BYTES
            or not hmac.compare_digest(
                source_blob_sha, _github_blob_sha(encrypted_checkpoint))):
        raise ValueError('source encrypted checkpoint SHA mismatch')
    try:
        plaintext = _cipher(primary_key).decrypt(encrypted_checkpoint)
        if len(plaintext) > MAX_PLAINTEXT_BYTES:
            raise ValueError('checkpoint is oversized')
        bundle = json.loads(plaintext)
    except (InvalidToken, UnicodeError, json.JSONDecodeError):
        raise ValueError('source encrypted checkpoint is invalid') from None
    verification = verify_audit_bundle(
        bundle, trusted_public_keys=trusted_public_keys)
    package = {
        'schema_version': SCHEMA,
        'source_blob_sha': source_blob_sha,
        'keyring_digest': _trusted_keyring_digest(trusted_public_keys),
        'bundle': bundle,
    }
    backup_data = _canonical(package)
    if len(backup_data) > MAX_RECOVERY_ARCHIVE_BYTES - 1024:
        raise ValueError('recovery archive too large')
    sealed = _cipher(recovery_key).encrypt(backup_data)
    if len(sealed) > MAX_RECOVERY_ARCHIVE_BYTES:
        raise ValueError('encrypted recovery archive too large')
    return {
        'private_encrypted_archive': sealed,
        'summary': {
            'backup_exported_as_bytes_only': True,
            'review_cycles_verified': verification['summary']['historical_review_cycles'],
            'distinct_recovery_key_required': True,
            'remote_or_local_files_written': False,
            'source_mutated': False,
            'restore_approved': False,
        },
    }


def inspect_offline_recovery_archive(
        archive, *, recovery_key, trusted_public_keys):
    """Check integrity and complete historic signatures before any recovery."""
    if (not isinstance(archive, bytes)
            or not 1 <= len(archive) <= MAX_RECOVERY_ARCHIVE_BYTES):
        raise ValueError('invalid or oversized encrypted recovery archive')
    try:
        plaintext = _cipher(recovery_key).decrypt(archive)
        if len(plaintext) > MAX_RECOVERY_ARCHIVE_BYTES - 1024:
            raise ValueError('invalid recovery archive length')
        payload = json.loads(plaintext)
    except (InvalidToken, UnicodeError, json.JSONDecodeError):
        raise ValueError('offline recovery archive decryption failed') from None
    if (not isinstance(payload, dict)
            or set(payload) != {
                'schema_version', 'source_blob_sha', 'keyring_digest', 'bundle'}
            or payload['schema_version'] != SCHEMA
            or not isinstance(payload['source_blob_sha'], str)
            or not _BLOB_SHA.fullmatch(payload['source_blob_sha'])
            or not hmac.compare_digest(
                str(payload['keyring_digest']),
                _trusted_keyring_digest(trusted_public_keys))):
        raise ValueError('recovery archive metadata or reviewer trust changed')
    verified = verify_audit_bundle(
        payload['bundle'], trusted_public_keys=trusted_public_keys)
    return {
        'private_bundle': payload['bundle'],
        'private_source_blob_sha': payload['source_blob_sha'],
        'summary': {
            'archive_integrity_verified': True,
            'review_cycles_verified': verified['summary']['historical_review_cycles'],
            'remote_github_state_verified': False,
            'source_drive_revisions_verified': False,
            'restoration_performed': False,
        },
    }


def prepare_offline_recovery_ciphertext(
        archive, *, recovery_key, new_primary_key, trusted_public_keys,
        approve_offline_recovery=False):
    """Prepare a NEW primary-key-encrypted artifact, NEVER upload it.

    A trusted operator must compare the private GitHub remote HEAD, assess
    any newer reviews, and re-scan Drive before separately approving a write.
    This function cannot authorize rollback or unattended migration.
    """
    if approve_offline_recovery is not True:
        raise ValueError('offline recovery needs deliberate manual approval')
    _check_distinct_keys(recovery_key, new_primary_key)
    checked = inspect_offline_recovery_archive(
        archive, recovery_key=recovery_key,
        trusted_public_keys=trusted_public_keys)
    plain = _canonical(checked['private_bundle'])
    if len(plain) > MAX_PLAINTEXT_BYTES:
        raise ValueError('recovery checkpoint exceeds size limit')
    new_cipher = _cipher(new_primary_key).encrypt(plain)
    if len(new_cipher) > MAX_CIPHERTEXT_BYTES:
        raise ValueError('recovered checkpoint ciphertext exceeds size limit')
    return {
        'private_reencrypted_checkpoint': new_cipher,
        'private_source_blob_sha': checked['private_source_blob_sha'],
        'summary': {
            'historical_reviews_reverified': True,
            'encrypted_checkpoint_prepared_only': True,
            'remote_write_performed': False,
            'remote_generation_recheck_required': True,
            'source_drive_revision_recheck_required': True,
            'rollback_protection_requires_external_review': True,
        },
    }
