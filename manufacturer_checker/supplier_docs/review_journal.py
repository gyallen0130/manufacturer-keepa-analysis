"""Private encrypted, append-only-by-contract review receipt journal (POSIX only).

Neither the inventory nor review journal is a public GitHub artifact. This
module runs no network calls and never authorizes a purchase or writes an
inventory baseline. Real reviewer authentication belongs to an external
trusted application, NOT to this module.
"""
import hashlib
import json
import os
import tempfile

from cryptography.fernet import InvalidToken

from .review_gate import _canonical, plan_review_retries
from .snapshot_store import (
    MAX_CIPHERTEXT_BYTES, _cipher, _existing_ciphertext, _private_directory,
)

JOURNAL_VERSION = 'supplier-private-review-journal-v1'


def _context_digest(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError('invalid inventory context')
    return hashlib.sha256(_canonical(snapshot)).hexdigest()


def _state(previous, current, receipts, signing_key, allowed_reviewers):
    # Validate all receipts against the exact input versions before persisting.
    plan_review_retries(
        previous, current, receipts=receipts, signing_key=signing_key,
        allowed_reviewers=allowed_reviewers)
    return {
        'schema_version': JOURNAL_VERSION,
        'previous_digest': _context_digest(previous),
        'current_digest': _context_digest(current),
        'receipts': list(receipts),
    }


def _decrypt_state(raw, *, cipher_key):
    try:
        plaintext = _cipher(cipher_key).decrypt(raw)
        if len(plaintext) > MAX_CIPHERTEXT_BYTES:
            raise ValueError('review journal payload too large')
        data = json.loads(plaintext)
    except (InvalidToken, UnicodeError, json.JSONDecodeError):
        raise ValueError('encrypted review journal failed validation') from None
    if not isinstance(data, dict):
        raise ValueError('invalid journal structure')
    return data


def read_encrypted_review_journal(path, *, cipher_key, signing_key,
                                  previous, current, allowed_reviewers):
    """Load signed records for exactly the same pair of inventory snapshots."""
    if cipher_key == signing_key:
        raise ValueError('encryption and reviewer signing keys must be distinct')
    p = _private_directory(path)
    payload = _existing_ciphertext(p)
    if payload is None:
        raise FileNotFoundError('review journal is not initialized')
    data = _decrypt_state(payload, cipher_key=cipher_key)
    expected = _state(previous, current, data.get('receipts'),
                      signing_key, allowed_reviewers)
    if data != expected:
        raise ValueError('review journal context mismatch')
    return expected['receipts'], hashlib.sha256(payload).hexdigest()


def write_encrypted_review_journal(path, *, cipher_key, signing_key,
                                   previous, current, receipts, allowed_reviewers,
                                   expected_revision=None):
    """Atomically create or monotonically append validated private receipts.

    New file refuses overwrite. Updates require a matching ciphertext SHA256
    and preserve all existing receipts in order (append-only by contract).
    Only one trusted writer process is supported; no distributed locks yet.
    """
    if cipher_key == signing_key:
        raise ValueError('encryption and reviewer signing keys must be distinct')
    state = _state(previous, current, receipts, signing_key, allowed_reviewers)
    path = _private_directory(path)
    original = _existing_ciphertext(path)
    if expected_revision is None:
        if original is not None:
            raise FileExistsError('review journal already exists')
    else:
        if (not isinstance(expected_revision, str) or original is None or
                hashlib.sha256(original).hexdigest() != expected_revision):
            raise ValueError('review journal revision mismatch')
        existing = _decrypt_state(original, cipher_key=cipher_key)
        if (not isinstance(existing.get('receipts'), list)
                or existing.get('schema_version') != JOURNAL_VERSION
                or existing.get('previous_digest') != state['previous_digest']
                or existing.get('current_digest') != state['current_digest']
                or state['receipts'][:len(existing['receipts'])] != existing['receipts']):
            raise ValueError('review journal cannot drop prior receipts')
        # Also ensure previous receipts pass signature and allowlist validation.
        _state(previous, current, existing['receipts'],
               signing_key, allowed_reviewers)

    plaintext = _canonical(state)
    if len(plaintext) > MAX_CIPHERTEXT_BYTES - 1024:
        raise ValueError('review journal too large')
    ciphertext = _cipher(cipher_key).encrypt(plaintext)
    if len(ciphertext) > MAX_CIPHERTEXT_BYTES:
        raise ValueError('encrypted review journal too large')

    fd, temp_path = tempfile.mkstemp(prefix='.pending-review-', dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(ciphertext)
            stream.flush()
            os.fsync(stream.fileno())
        if expected_revision is None:
            os.link(temp_path, str(path))
        else:
            os.replace(temp_path, str(path))
        parent_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return hashlib.sha256(ciphertext).hexdigest()
