"""Encrypted, explicit-commit inventory state for an approved Linux workspace.

This module NEVER discovers folders, downloads documents, runs analyses, or
uploads data. File IDs and modification markers are sensitive: snapshots must
not enter GitHub, stdout, shared Colab notebooks, or unencrypted cloud storage.

A caller-supplied Fernet key must be kept OUTSIDE the snapshot directory.
This is a POSIX/Linux store for a private directory (0700) and files (0600).
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

from cryptography.fernet import Fernet, InvalidToken
from .drive_delta import _valid_id, _validate_snapshot, plan_explicit_folder_set

MAX_CIPHERTEXT_BYTES = 5_000_000
MAX_FOLDERS = 200


def _validated_set(snapshots):
    if (not isinstance(snapshots, dict) or not snapshots
            or len(snapshots) > MAX_FOLDERS):
        raise ValueError('invalid approved inventory state')
    seen = set()
    for folder_id, data in snapshots.items():
        if not _valid_id(folder_id) or not isinstance(data, dict):
            raise ValueError('invalid inventory folder')
        if folder_id != data.get('folder_id'):
            raise ValueError('inventory folder mismatch')
        files = _validate_snapshot(data)
        if seen.intersection(files):
            raise ValueError('duplicate file across approved folders')
        seen.update(files)
    return snapshots


def _private_directory(path):
    if os.name != 'posix':
        raise OSError('private inventory requires a POSIX runtime')
    p = Path(path)
    directory = p.parent
    meta = directory.lstat()
    if (not stat.S_ISDIR(meta.st_mode) or stat.S_IMODE(meta.st_mode) != 0o700
            or meta.st_uid != os.getuid()):
        raise PermissionError('inventory directory must be owned and mode 0700')
    if not p.name or p.name in ('.', '..'):
        raise ValueError('invalid inventory file path')
    return p


def _existing_ciphertext(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid() or info.st_size > MAX_CIPHERTEXT_BYTES):
        raise PermissionError('inventory file must be owned and mode 0600')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(str(path), flags)
    try:
        checked = os.fstat(fd)
        if (not stat.S_ISREG(checked.st_mode)
                or stat.S_IMODE(checked.st_mode) != 0o600
                or checked.st_uid != os.getuid()):
            raise PermissionError('unsafe inventory file')
        data = os.read(fd, MAX_CIPHERTEXT_BYTES + 1)
        if len(data) > MAX_CIPHERTEXT_BYTES:
            raise ValueError('inventory state exceeds size limit')
        return data
    finally:
        os.close(fd)


def _cipher(key):
    if not isinstance(key, bytes):
        raise ValueError('inventory encryption key must be bytes')
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:
        raise ValueError('invalid inventory encryption key') from None


def read_encrypted_inventory(path, *, key):
    """Return (private snapshot set, opaque revision); no logging.

    An absent state is NOT treated as a baseline. The caller must explicitly
    decide whether to initialize. Invalid keys, corrupted files and unsafe
    permissions all stop the process.
    """
    p = _private_directory(path)
    payload = _existing_ciphertext(p)
    if payload is None:
        raise FileNotFoundError('inventory state not initialized')
    try:
        plaintext = _cipher(key).decrypt(payload)
        if len(plaintext) > MAX_CIPHERTEXT_BYTES:
            raise ValueError('inventory payload too large')
        state = json.loads(plaintext)
        return _validated_set(state), hashlib.sha256(payload).hexdigest()
    except (InvalidToken, UnicodeError, json.JSONDecodeError):
        raise ValueError('encrypted inventory could not be verified') from None


def write_encrypted_inventory(path, *, key, snapshots, expected_revision=None):
    """Atomically persist an *approved* state; caller must finalize first.

    expected_revision=None creates a new file and refuses any overwrite.
    An update requires a matching ciphertext revision from a previous read.
    This is not a cross-process transaction; only one orchestrator may write.
    """
    _validated_set(snapshots)
    p = _private_directory(path)
    original = _existing_ciphertext(p)
    if expected_revision is None:
        if original is not None:
            raise FileExistsError('inventory state already exists')
    else:
        if (not isinstance(expected_revision, str)
                or not original
                or hashlib.sha256(original).hexdigest() != expected_revision):
            raise ValueError('inventory revision mismatch')

    plaintext = json.dumps(snapshots, ensure_ascii=False,
                           sort_keys=True, separators=(',', ':')).encode('utf-8')
    if len(plaintext) > MAX_CIPHERTEXT_BYTES - 1024:
        raise ValueError('inventory too large')
    ciphertext = _cipher(key).encrypt(plaintext)
    if len(ciphertext) > MAX_CIPHERTEXT_BYTES:
        raise ValueError('encrypted inventory too large')

    fd, temp_path = tempfile.mkstemp(prefix='.pending-inventory-', dir=str(p.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(ciphertext)
            stream.flush()
            os.fsync(stream.fileno())
        if expected_revision is None:
            # link, unlike rename, cannot replace an existing baseline.
            os.link(temp_path, str(p))
        else:
            os.replace(temp_path, str(p))
        parent_fd = os.open(str(p.parent), os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return hashlib.sha256(ciphertext).hexdigest()


def finalize_inventory(previous, current, *, completed_locations=(),
                       approve_initial_baseline=False, reviewed_unavailable=()):
    """Gate baseline advancement on full, explicitly acknowledged processing.

    No snapshot is saved by this function. Initial baselines skip old files
    ONLY if explicitly approved. Every new/changed file must be acknowledged
    before its revision may advance. Unavailable files always require review,
    never automatic deletion. On failure, retain the previous full baseline.
    """
    _validated_set(current)
    if previous is not None:
        _validated_set(previous)
    plan = plan_explicit_folder_set(previous, current)
    if previous is None:
        if not approve_initial_baseline:
            raise ValueError('initial baseline requires explicit approval')
        if completed_locations or reviewed_unavailable:
            raise ValueError('baseline cannot include completed work')
        return current
    if approve_initial_baseline:
        raise ValueError('initial baseline approval not valid on update')
    expected = {tuple(item) for item in plan['candidate_locations']}
    missing = {tuple(item) for item in plan['unavailable_locations']}
    try:
        done = [tuple(item) for item in completed_locations]
        reviewed = [tuple(item) for item in reviewed_unavailable]
    except TypeError:
        raise ValueError('invalid completion records') from None
    if (len(done) != len(set(done)) or len(reviewed) != len(set(reviewed))
            or set(done) != expected or set(reviewed) != missing):
        raise ValueError('unconfirmed changes or inaccessible files')
    return current


def review_queue(previous, current):
    """Return inert, private per-file review queue. No network or processing.

    Google Sheets can eventually be parsed via its readonly API. Binary Excel,
    CSV and TSV files need a separate approved read-only acquisition step.
    """
    plan = plan_explicit_folder_set(previous, current)
    queue = []
    for folder_id, file_id in plan['candidate_locations']:
        meta = current[folder_id]['files'][file_id]
        queue.append({
            'folder_id': folder_id,
            'file_id': file_id,
            'mime_type': meta['mime_type'],
            'status': ('sheets_review_required'
                       if meta['mime_type'] == 'application/vnd.google-apps.spreadsheet'
                       else 'unsupported_download_review_required'),
        })
    return {'is_baseline': plan['is_baseline'],
            'summary': plan['summary'],
            'private_queue': queue,
            'unavailable_locations': plan['unavailable_locations']}
