"""Single-run GitHub Actions sink: encrypted owner-only results, no plaintext.

This is a PRIVATE-REPOSITORY, trusted-GitHub-runner-only artifact staging
adapter. It never calls GitHub, Google, uploads anything, nor emits a path or
secret to the runner log. Artifact upload (if later enabled) is separate and
must point ONLY at the fixed encrypted JSON file.

Encrypted result content is still sensitive metadata; use a private repo,
short artifact retention, independently pinned recipient public key and
reviewed spending controls. GitHub Actions storage may count toward billing.
"""
import json
import os
from pathlib import Path
import stat

from .private_result_envelope import (
    MAX_ENVELOPE_BYTES, VERSION, _FIELDS, _aad,
)

FILENAME = 'supplier-owner-encrypted-result.json'


def write_encrypted_owner_result(envelope, *, runner_temp):
    """Create exactly one encrypted result file, exclusive and 0600 on POSIX.

    Requires the caller to have verified the private workflow, WIF and
    recipient fingerprint separately. Never overwrite. Never write plaintext.
    """
    if (not isinstance(envelope, dict)
            or set(envelope) != _FIELDS
            or envelope['schema_version'] != VERSION):
        raise ValueError('encrypted owner result format is not approved')
    raw = _aad(envelope)
    if not 1 <= len(raw) <= MAX_ENVELOPE_BYTES:
        raise ValueError('encrypted owner result exceeds bound')
    if not isinstance(runner_temp, str):
        raise ValueError('GitHub runner temp path required')
    root = Path(runner_temp)
    if not root.is_absolute():
        raise ValueError('GitHub runner temp path must be absolute')
    info = root.lstat()
    if (not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or (hasattr(info, 'st_file_attributes')
                and info.st_file_attributes & getattr(
                    stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))):
        raise PermissionError('untrusted temporary directory')
    output = root / FILENAME
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    flags |= getattr(os, 'O_NOFOLLOW', 0)
    flags |= getattr(os, 'O_BINARY', 0)
    fd = os.open(str(output), flags, 0o600)
    try:
        if os.name == 'posix':
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            fd = -1
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        if fd != -1:
            os.close(fd)
        output.unlink()
        raise
    return {'encrypted_result_file_created': True,
            'file_overwritten': False,
            'plaintext_file_created': False,
            'api_calls': 0}


def stage_owner_report(report, *, runner_temp,
                       recipient_public_key_b64,
                       trusted_fingerprint_sha256):
    """Encrypt in memory first, then store just authenticated ciphertext."""
    from .private_result_envelope import seal_private_inspections
    envelope = seal_private_inspections(
        report, recipient_public_key_b64=recipient_public_key_b64,
        trusted_fingerprint_sha256=trusted_fingerprint_sha256)
    return write_encrypted_owner_result(envelope, runner_temp=runner_temp)
