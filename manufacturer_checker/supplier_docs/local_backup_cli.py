"""Manual, offline encrypted-backup VERIFY/COPY for a trusted Windows PC.

- No network, GitHub Actions, Colab, Google or Amazon API calls.
- NO --key, environment-key, stdin-pipe, secret file or debug mode.
- Recovery Fernet key is entered using getpass only in a real TTY.
- A separately pinned SHA-256 fingerprint of the trusted PUBLIC-key file is
  mandatory; checking the public-key file against its own hash is NOT trust.
- No restore, overwrite, decryption-to-disk, archive creation, key generation,
  automated scheduler or production integration.

The program cannot determine actual NTFS ACL, BitLocker, malware or physical
device independence. Interactive operator checks are REQUIRED but do not prove
those properties. Source keyring file contains PUBLIC keys only.
"""
import argparse
import base64
import binascii
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .local_backup_store import (
    read_verified_local_backup, copy_backup_to_separate_location,
)
from .review_gate import ACTOR_PATTERN
from .snapshot_store import _cipher

SCHEMA = 'supplier-trusted-reviewers-v1'
_MAX_KEYRING_BYTES = 16000
_DIGEST = re.compile(r'^[0-9a-f]{64}$')
_PUBLIC_KEY_B64 = re.compile(r'^[A-Za-z0-9+/]{43}=$')


class _SafeParser(argparse.ArgumentParser):
    """Never include an unknown command-line argument in a diagnostic."""

    def error(self, message):
        self.exit(2, 'Invalid command-line options (no secrets allowed).\n')


def make_parser():
    parser = _SafeParser(
        description='Verify or copy an encrypted local backup; NO cloud access.',
        allow_abbrev=False)
    sub = parser.add_subparsers(dest='operation', required=True)
    for name in ('verify', 'copy'):
        command = sub.add_parser(name, parser_class=_SafeParser,
                                 allow_abbrev=False)
        command.add_argument('--source', required=True)
        command.add_argument('--public-keyring', required=True)
        command.add_argument('--trusted-keyring-sha256', required=True)
        if name == 'copy':
            command.add_argument('--destination', required=True)
    return parser


def _read_small_public_file(path):
    """Reject symlinks/reparse points and oversized untrusted keyring input.

    A caller must verify the fingerprint from an INDEPENDENT trusted location.
    """
    p = Path(path)
    if not p.is_absolute():
        raise ValueError('trusted keyring path must be absolute')
    before = p.lstat()
    if (not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or (hasattr(before, 'st_file_attributes')
                and before.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
            or not 1 <= before.st_size <= _MAX_KEYRING_BYTES):
        raise ValueError('invalid trusted public-keyring file')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    flags |= getattr(os, 'O_BINARY', 0)
    fd = os.open(str(p), flags)
    try:
        after = os.fstat(fd)
        if (not stat.S_ISREG(after.st_mode)
                or after.st_ino != before.st_ino
                or after.st_dev != before.st_dev
                or not 1 <= after.st_size <= _MAX_KEYRING_BYTES):
            raise ValueError('public-keyring file changed while reading')
        with os.fdopen(fd, 'rb') as stream:
            fd = -1
            raw = stream.read(_MAX_KEYRING_BYTES + 1)
    finally:
        if fd != -1:
            os.close(fd)
    if not 1 <= len(raw) <= _MAX_KEYRING_BYTES:
        raise ValueError('public-keyring is oversized')
    return raw


def load_pinned_public_keys(path, *, trusted_keyring_sha256):
    """Strict, public-only Ed25519 keyring bound to independent SHA-256."""
    if (not isinstance(trusted_keyring_sha256, str)
            or not _DIGEST.fullmatch(trusted_keyring_sha256)):
        raise ValueError('external trusted keyring SHA-256 required')
    raw = _read_small_public_file(path)
    if not hmac.compare_digest(
            hashlib.sha256(raw).hexdigest(), trusted_keyring_sha256):
        raise ValueError('public keyring does not match independently pinned SHA-256')
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError('invalid trusted public-keyring format') from None
    if (not isinstance(data, dict)
            or set(data) != {'schema_version', 'reviewers'}
            or data['schema_version'] != SCHEMA
            or not isinstance(data['reviewers'], dict)
            or not 1 <= len(data['reviewers']) <= 32):
        raise ValueError('invalid trusted public-keyring structure')
    trusted = {}
    for reviewer, value in data['reviewers'].items():
        if (not isinstance(reviewer, str)
                or not ACTOR_PATTERN.fullmatch(reviewer)
                or not isinstance(value, str)
                or not _PUBLIC_KEY_B64.fullmatch(value)):
            raise ValueError('invalid trusted reviewer public key')
        try:
            raw_pub = base64.b64decode(value, validate=True)
            if len(raw_pub) != 32:
                raise ValueError('invalid Ed25519 public key length')
            trusted[reviewer] = Ed25519PublicKey.from_public_bytes(raw_pub)
        except (ValueError, binascii.Error):
            raise ValueError('invalid trusted Ed25519 public key') from None
    return trusted


def _confirmation(ask, label, expected):
    result = ask(label + ' Type ' + expected + ' to continue: ')
    if result != expected:
        raise PermissionError('explicit local backup confirmation required')


def perform_local_operation(
        options, *, secret_reader, confirmation_reader):
    """Dependency-injected core; returns ONLY redacted operation counts.

    Interactive production entrypoint always requires real terminal. Tests
    inject synthetic one-time recovery keys and confirmation functions.
    """
    if options.operation not in ('verify', 'copy'):
        raise ValueError('unsupported operation')
    if os.name == 'nt':
        _confirmation(
            confirmation_reader,
            'Windows folder ACL and drive encryption independently checked.',
            'WINDOWS-REVIEWED')
    else:
        _confirmation(
            confirmation_reader,
            'Trusted local owner-only folder independently checked.',
            'LOCAL-REVIEWED')

    if options.operation == 'copy':
        _confirmation(
            confirmation_reader,
            'Destination is a SEPARATE PHYSICAL DEVICE and contains no '
            'unwanted synchronization. This is not verified by software.',
            'SEPARATE-DEVICE')
        _confirmation(
            confirmation_reader,
            'Create encrypted copy only; never overwrite an existing file.',
            'COPY-ONCE')

    keys = load_pinned_public_keys(
        options.public_keyring,
        trusted_keyring_sha256=options.trusted_keyring_sha256)
    secret = secret_reader('Recovery key (input hidden; never logged): ')
    if not isinstance(secret, str):
        raise ValueError('recovery key must be entered interactively')
    # Only a 44-character URL-safe Fernet key is acceptable; never log it.
    if len(secret) != 44:
        raise ValueError('invalid recovery key')
    key = secret.encode('ascii')
    _cipher(key)  # validates before touching backup

    if options.operation == 'verify':
        verified = read_verified_local_backup(
            options.source, recovery_key=key,
            trusted_public_keys=keys,
            windows_storage_reviewed=(os.name == 'nt'))
        return {
            'operation': 'verify',
            'encrypted_backup_verified': True,
            'review_cycles_verified':
                verified['summary']['signed_review_cycles_verified'],
            'files_created': 0,
            'api_calls': 0,
        }
    copied = copy_backup_to_separate_location(
        options.source, options.destination, recovery_key=key,
        trusted_public_keys=keys,
        approve_independent_copy=True,
        operator_confirmed_separate_device=True,
        windows_storage_reviewed=(os.name == 'nt'))
    return {
        'operation': 'copy',
        'encrypted_copy_created': copied['independent_copy_created'],
        'review_cycles_verified': copied['signed_review_cycles_verified'],
        'device_independence_verified_by_code': False,
        'api_calls': 0,
    }


def main(argv=None, *, input_stream=None, error_stream=None,
         confirmation_reader=None, secret_reader=None):
    """Never echo sensitive argv contents or Python tracebacks on failure."""
    stderr = error_stream or sys.stderr
    stdin = input_stream or sys.stdin
    args = make_parser().parse_args(argv)
    if not stdin.isatty() or not stderr.isatty():
        stderr.write('A local interactive terminal is required. No operation.\n')
        return 2
    try:
        result = perform_local_operation(
            args,
            confirmation_reader=confirmation_reader or input,
            secret_reader=secret_reader or getpass.getpass)
    except (OSError, PermissionError, ValueError, FileExistsError):
        stderr.write(
            'Backup operation refused. Check keyring trust, storage protection, '
            'key, approvals and file integrity locally; details are hidden.\n')
        return 1
    # No raw path, source metadata, reviewer IDs, keys or traceback.
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
