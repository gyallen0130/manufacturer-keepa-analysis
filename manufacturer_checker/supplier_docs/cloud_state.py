"""Development-only optimistic-concurrency adapter for private GCS state.

Only caller-supplied Google Cloud Storage Blob objects are used; there are no
default projects, bucket discovery, deployment actions or network calls on
import. Never use on a production SP-API bucket. All actual calls require an
explicit blob supplied by an authenticated, dedicated supplier-only runtime.

Inventory and review journal are SEPARATE objects and do not form a
cross-object transaction. Do not enable unattended periodic execution until
one-writer orchestration, object versioning and recovery are established.
"""
import json
from cryptography.fernet import InvalidToken

from .snapshot_store import (
    MAX_CIPHERTEXT_BYTES, _cipher, _validated_set,
)
from .review_journal import _state, _decrypt_state

OBJECT_NAMES = {
    'inventory': 'supplier-docs/inventory.enc',
    'journal': 'supplier-docs/review-journal.enc',
}


def _check_blob(blob, purpose):
    """Disallow accidental use of existing SP-API storage resources."""
    if purpose not in OBJECT_NAMES:
        raise ValueError('unsupported private object purpose')
    bucket = getattr(getattr(blob, 'bucket', None), 'name', None)
    if (not isinstance(bucket, str)
            or not bucket.startswith('supplier-docs-state-')
            or getattr(blob, 'name', None) != OBJECT_NAMES[purpose]):
        raise ValueError('supplier-specific private object required')


def _read(blob, *, cipher_key, purpose):
    _check_blob(blob, purpose)
    blob.reload(timeout=30)
    gen = getattr(blob, 'generation', None)
    size = getattr(blob, 'size', None)
    if (type(gen) is not int or gen < 1 or type(size) is not int
            or size < 1 or size > MAX_CIPHERTEXT_BYTES):
        raise ValueError('unsafe or oversized object metadata')
    raw = blob.download_as_bytes(if_generation_match=gen, timeout=30)
    if (not isinstance(raw, bytes) or not raw
            or len(raw) > MAX_CIPHERTEXT_BYTES):
        raise ValueError('invalid encrypted object payload')
    # A concurrent overwrite either fails generation check or is prevented by
    # the GCS generation precondition in the underlying Cloud Storage client.
    return raw, gen


def _write(blob, *, cipher_key, purpose, plaintext, expected_generation):
    _check_blob(blob, purpose)
    if (type(expected_generation) is not int
            or expected_generation < 0):
        raise ValueError('explicit GCS generation precondition required')
    if not isinstance(plaintext, bytes) or len(plaintext) > MAX_CIPHERTEXT_BYTES - 1024:
        raise ValueError('private state payload exceeds size limit')
    ciphertext = _cipher(cipher_key).encrypt(plaintext)
    if len(ciphertext) > MAX_CIPHERTEXT_BYTES:
        raise ValueError('encrypted state exceeds size limit')
    blob.upload_from_string(
        ciphertext,
        content_type='application/octet-stream',
        if_generation_match=expected_generation,
        timeout=30,
    )
    return {'written': True, 'generation_precondition_used': True}


def read_cloud_inventory(blob, *, cipher_key):
    """Return (validated private inventory, GCS generation) or fail closed."""
    raw, generation = _read(blob, cipher_key=cipher_key, purpose='inventory')
    try:
        plain = _cipher(cipher_key).decrypt(raw)
        content = json.loads(plain)
        _validated_set(content)
        return content, generation
    except (InvalidToken, UnicodeError, json.JSONDecodeError):
        raise ValueError('encrypted supplier inventory invalid') from None


def write_cloud_inventory(blob, *, cipher_key, approved_snapshots,
                          expected_generation):
    """Persist only a separately approved snapshot; never performs approval.

    expected_generation=0 is create-only. An update requires the generation
    previously read; storage rejects races with 412 precondition failure.
    """
    _validated_set(approved_snapshots)
    plaintext = json.dumps(
        approved_snapshots, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')
    return _write(blob, cipher_key=cipher_key, purpose='inventory',
                  plaintext=plaintext, expected_generation=expected_generation)


def read_cloud_review_journal(blob, *, cipher_key, signing_key,
                              previous, current, allowed_reviewers):
    """Return (private signed receipts, GCS generation) or reject mismatch."""
    if cipher_key == signing_key:
        raise ValueError('review signing and encryption secrets must differ')
    raw, generation = _read(blob, cipher_key=cipher_key, purpose='journal')
    data = _decrypt_state(raw, cipher_key=cipher_key)
    expected = _state(previous, current, data.get('receipts'),
                      signing_key, allowed_reviewers)
    if data != expected:
        raise ValueError('encrypted review journal does not match inventory')
    return expected['receipts'], generation


def write_cloud_review_journal(blob, *, cipher_key, signing_key,
                               previous, current, receipts, allowed_reviewers,
                               expected_generation):
    """Write journal only with a GCS generation guard and append-only check."""
    if cipher_key == signing_key:
        raise ValueError('review signing and encryption secrets must differ')
    proposed = _state(previous, current, receipts,
                      signing_key, allowed_reviewers)
    if expected_generation != 0:
        existing, generation = read_cloud_review_journal(
            blob, cipher_key=cipher_key, signing_key=signing_key,
            previous=previous, current=current,
            allowed_reviewers=allowed_reviewers)
        if generation != expected_generation:
            raise ValueError('review journal revision mismatch')
        if proposed['receipts'][:len(existing)] != existing:
            raise ValueError('review journal records cannot be removed or changed')
    plaintext = json.dumps(
        proposed, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')
    return _write(blob, cipher_key=cipher_key, purpose='journal',
                  plaintext=plaintext, expected_generation=expected_generation)
