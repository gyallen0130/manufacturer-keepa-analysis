"""Owner-side LOCAL X25519 key vault and encrypted supplier-result reader.

Pure local I/O. No Google/GitHub/network calls, cloud key stores, or costs.
Never pass passphrases/private keys through argv, environment, logs or files
outside this passphrase-encrypted vault. A trustworthy OS, strong independent
passphrase, separate backup, private directory and full-disk encryption matter.

On Windows Python cannot reliably prove NTFS ACL / BitLocker settings. Thus
the caller MUST review them independently. Explicit confirmation flags do
not independently verify ACL, drive encryption or cloud sync.
"""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .private_result_envelope import (
    HEX_SHA256, MAX_ENVELOPE_BYTES, _aad, _decode, _encode,
    open_private_inspections, recipient_public_key_b64,
)

VAULT_SCHEMA = 'supplier-owner-x25519-passphrase-vault-v1'
SALT_BYTES = 16
NONCE_BYTES = 12
SCRYPT_N, SCRYPT_R, SCRYPT_P = 32768, 8, 1
MAX_VAULT_BYTES = 3000
MAX_EXPORT_BYTES = 1_600_000
_VAULT_FIELDS = {
    'schema_version', 'kdf', 'salt_b64', 'nonce_b64',
    'recipient_public_key_b64', 'recipient_fingerprint_sha256',
    'encrypted_private_key_b64',
}
_REPARSE = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)


def _passphrase_bytes(passphrase, *, creating=False):
    if not isinstance(passphrase, str) or not 16 <= len(passphrase) <= 512:
        raise ValueError('a long private passphrase is required')
    if '\x00' in passphrase:
        raise ValueError('invalid private passphrase')
    encoded = passphrase.encode('utf-8')
    if len(encoded) > 2048:
        raise ValueError('private passphrase exceeds length limit')
    return encoded


def _derive(passphrase, salt):
    return Scrypt(
        salt=salt, length=32,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
    ).derive(_passphrase_bytes(passphrase))


def _safe_path(path, *, storage_reviewed, private_parent):
    p = Path(path)
    if not p.is_absolute() or p.name in ('', '.', '..'):
        raise ValueError('absolute trusted local path required')
    if os.name == 'nt':
        if p.drive.startswith('\\\\'):
            raise ValueError('network share is not approved local storage')
        if storage_reviewed is not True:
            raise PermissionError('Windows local ACL and encryption review required')
    elif os.name != 'posix':
        raise OSError('unsupported local filesystem')
    parent = p.parent
    if not parent.is_dir():
        raise ValueError('local private folder must exist before use')
    for item in (parent, *parent.parents):
        if (item / '.git').exists():
            raise PermissionError('supplier secrets cannot be stored in a Git working tree')
        info = item.lstat()
        if (not stat.S_ISDIR(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or (hasattr(info, 'st_file_attributes')
                    and info.st_file_attributes & _REPARSE)):
            raise PermissionError('unsafe linked or redirected folder')
    if private_parent and os.name == 'posix':
        st = parent.stat()
        if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
            raise PermissionError('private folder must be owner-only 0700')
    return p


def _read_once(p, *, max_bytes, owner_only):
    before = p.lstat()
    if (not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or (hasattr(before, 'st_file_attributes')
                and before.st_file_attributes & _REPARSE)
            or not 1 <= before.st_size <= max_bytes):
        raise ValueError('untrusted or oversized local file')
    if owner_only and os.name == 'posix':
        if before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) != 0o600:
            raise PermissionError('private file must be owner-only 0600')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0)
    flags |= getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(str(p), flags)
    try:
        after = os.fstat(fd)
        if (not stat.S_ISREG(after.st_mode)
                or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
                or not 1 <= after.st_size <= max_bytes):
            raise ValueError('file changed during local read')
        with os.fdopen(fd, 'rb') as handle:
            fd = -1
            result = handle.read(max_bytes + 1)
    finally:
        if fd >= 0:
            os.close(fd)
    if not 1 <= len(result) <= max_bytes:
        raise ValueError('local file is oversized')
    return result


def _create_once(p, data):
    if p.is_symlink():
        raise FileExistsError('local file already exists')
    fd = os.open(
        str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL |
        getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0),
        0o600)
    try:
        if os.name == 'posix':
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            fd = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        if fd >= 0:
            os.close(fd)
        p.unlink()
        raise


def _vault_header(vault):
    return {key: value for key, value in vault.items()
            if key != 'encrypted_private_key_b64'}


def create_owner_key_vault(path, *, passphrase,
                           approve_key_creation=False,
                           windows_storage_reviewed=False):
    """Create-once password-encrypted vault, return PUBLIC recipient details.

    The vault file is itself valuable: loss of the file or its passphrase
    makes all GitHub encrypted results for this recipient unrecoverable.
    Back it up securely and separately from its passphrase before real use.
    """
    if approve_key_creation is not True:
        raise ValueError('owner key creation must be explicitly approved')
    p = _safe_path(
        path, storage_reviewed=windows_storage_reviewed, private_parent=True)
    _passphrase_bytes(passphrase, creating=True)
    if p.exists() or p.is_symlink():
        raise FileExistsError('owner key vault already exists')
    private = X25519PrivateKey.generate()
    raw_private = private.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption())
    public = recipient_public_key_b64(private)
    fingerprint = hashlib.sha256(base64.b64decode(public)).hexdigest()
    salt, nonce = os.urandom(SALT_BYTES), os.urandom(NONCE_BYTES)
    header = {
        'schema_version': VAULT_SCHEMA,
        'kdf': {'algorithm': 'scrypt', 'n': SCRYPT_N,
                'r': SCRYPT_R, 'p': SCRYPT_P},
        'salt_b64': _encode(salt), 'nonce_b64': _encode(nonce),
        'recipient_public_key_b64': public,
        'recipient_fingerprint_sha256': fingerprint,
    }
    ciphertext = AESGCM(_derive(passphrase, salt)).encrypt(
        nonce, raw_private, _aad(header))
    vault = {**header, 'encrypted_private_key_b64': _encode(ciphertext)}
    payload = _aad(vault)
    if len(payload) > MAX_VAULT_BYTES:
        raise ValueError('owner vault exceeds size limit')
    _create_once(p, payload)
    return {'public_key_b64': public, 'fingerprint_sha256': fingerprint,
            'private_key_printed': False, 'cloud_calls': 0,
            'vault_created': True}


def unlock_owner_private_key(path, *, passphrase,
                             trusted_fingerprint_sha256,
                             windows_storage_reviewed=False):
    """Decrypt only in memory after matching independently trusted pin."""
    if (not isinstance(trusted_fingerprint_sha256, str)
            or not HEX_SHA256.fullmatch(trusted_fingerprint_sha256)):
        raise ValueError('independently pinned recipient fingerprint required')
    p = _safe_path(
        path, storage_reviewed=windows_storage_reviewed, private_parent=True)
    try:
        vault = json.loads(_read_once(
            p, max_bytes=MAX_VAULT_BYTES, owner_only=True))
    except (ValueError, UnicodeError, json.JSONDecodeError):
        raise ValueError('private owner vault format rejected') from None
    if (not isinstance(vault, dict) or set(vault) != _VAULT_FIELDS
            or vault['schema_version'] != VAULT_SCHEMA
            or vault['kdf'] != {'algorithm': 'scrypt', 'n': SCRYPT_N,
                                'r': SCRYPT_R, 'p': SCRYPT_P}):
        raise ValueError('untrusted owner vault format or KDF parameters')
    pub = _decode(vault['recipient_public_key_b64'], size=32)
    expected = hashlib.sha256(pub).hexdigest()
    if (not hmac.compare_digest(expected, trusted_fingerprint_sha256)
            or not hmac.compare_digest(
                vault['recipient_fingerprint_sha256'], expected)):
        raise ValueError('owner recipient fingerprint does not match trusted pin')
    salt = _decode(vault['salt_b64'], size=SALT_BYTES)
    nonce = _decode(vault['nonce_b64'], size=NONCE_BYTES)
    encrypted = _decode(vault['encrypted_private_key_b64'], size=48)
    try:
        raw = AESGCM(_derive(passphrase, salt)).decrypt(
            nonce, encrypted, _aad(_vault_header(vault)))
        private = X25519PrivateKey.from_private_bytes(raw)
    except (InvalidTag, ValueError):
        raise ValueError('owner vault unlock failed') from None
    if not hmac.compare_digest(
            recipient_public_key_b64(private), vault['recipient_public_key_b64']):
        raise ValueError('owner vault private/public key mismatch')
    return private


def read_owner_encrypted_artifact(
        vault_path, artifact_path, *, passphrase,
        trusted_fingerprint_sha256, windows_storage_reviewed=False):
    """Decrypt a downloaded encrypted artifact in memory; never log or save."""
    private = unlock_owner_private_key(
        vault_path, passphrase=passphrase,
        trusted_fingerprint_sha256=trusted_fingerprint_sha256,
        windows_storage_reviewed=windows_storage_reviewed)
    source = _safe_path(
        artifact_path, storage_reviewed=windows_storage_reviewed,
        private_parent=False)
    try:
        envelope = json.loads(_read_once(
            source, max_bytes=MAX_ENVELOPE_BYTES, owner_only=False))
    except (UnicodeError, ValueError, json.JSONDecodeError):
        raise ValueError('encrypted artifact is invalid') from None
    return open_private_inspections(
        envelope, recipient_private_key=private,
        trusted_fingerprint_sha256=trusted_fingerprint_sha256)


def export_owner_inspections(
        vault_path, artifact_path, output_path, *, passphrase,
        trusted_fingerprint_sha256, approve_plaintext_export=False,
        windows_storage_reviewed=False):
    """Explicitly export plaintext ONLY into an owner-protected local file.

    Plaintext is sensitive even though the downloaded source was encrypted.
    NEVER export into a synced/shared folder, unencrypted device or public CI.
    """
    if approve_plaintext_export is not True:
        raise ValueError('plaintext export requires explicit approval')
    dest = _safe_path(
        output_path, storage_reviewed=windows_storage_reviewed,
        private_parent=True)
    if dest.exists() or dest.is_symlink():
        raise FileExistsError('owner plaintext output already exists')
    result = read_owner_encrypted_artifact(
        vault_path, artifact_path, passphrase=passphrase,
        trusted_fingerprint_sha256=trusted_fingerprint_sha256,
        windows_storage_reviewed=windows_storage_reviewed)
    payload = json.dumps(
        result, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')
    if not 1 <= len(payload) <= MAX_EXPORT_BYTES:
        raise ValueError('decrypted owner result exceeds size limit')
    _create_once(dest, payload)
    return {'plaintext_file_created': True, 'file_overwritten': False,
            'detail_rows_logged': False, 'cloud_calls': 0}
