"""Local, one-time encrypted audit archive storage for a trusted PC.

This adapter *only* saves/verifies an ALREADY ENCRYPTED recovery archive.
It never acquires cloud credentials, scans a Google Drive folder, invokes
GitHub, creates encryption/signing keys, uploads backups or restores state.

POSIX: requires an owned 0700 parent and enforces 0600 files. Windows:
requires an explicit operator declaration that the destination is a private
local NTFS folder, its ACLs and drive encryption have been checked. Python's
chmod() does NOT establish trustworthy Windows NTFS ACL isolation; no claim
that this module validates ACLs, BitLocker or the physical storage medium.

Files are create-only (O_EXCL): an existing archive is NEVER overwritten.
Windows junction/reparse-point races are not fully addressed by Python's
portable filesystem API; use only a trusted local single-user directory.
"""
import os
from pathlib import Path
import stat

from .offline_recovery_archive import (
    MAX_RECOVERY_ARCHIVE_BYTES, inspect_offline_recovery_archive,
)

_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)


def _checked_location(path, *, windows_storage_reviewed):
    p = Path(path)
    if not p.is_absolute() or p.name in ("", ".", ".."):
        raise ValueError("explicit absolute backup file path required")
    if os.name == "nt":
        if windows_storage_reviewed is not True:
            raise PermissionError(
                "operator must review Windows ACL and disk encryption")
    elif os.name != "posix":
        raise OSError("unsupported local backup filesystem")

    parent = p.parent
    if not parent.is_dir():
        raise ValueError("backup folder must exist before use")
    # Check the entire path. Do not accept linked directories to a more
    # permissive location. This is best-effort, not a sandbox or race lock.
    for ancestor in (parent, *parent.parents):
        info = ancestor.lstat()
        if (not stat.S_ISDIR(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or (info.st_file_attributes & _REPARSE
                    if hasattr(info, 'st_file_attributes') else False)):
            raise PermissionError("linked or unsafe backup directory")
    info = parent.lstat()
    if os.name == "posix":
        if (info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise PermissionError("backup folder must be owner-only 0700")
    return p


def _verify(archive, *, recovery_key, trusted_public_keys):
    checked = inspect_offline_recovery_archive(
        archive, recovery_key=recovery_key,
        trusted_public_keys=trusted_public_keys)
    return checked['summary']['review_cycles_verified']


def _create_once(p, archive):
    if p.is_symlink():
        raise FileExistsError("backup destination is a symbolic link")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_BINARY", 0)
    fd = os.open(str(p), flags, 0o600)
    created = True
    try:
        if os.name == "posix":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(archive)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "posix":
            folder_fd = os.open(str(p.parent), os.O_RDONLY)
            try:
                os.fsync(folder_fd)
            finally:
                os.close(folder_fd)
    except BaseException:
        if fd != -1:
            os.close(fd)
        if created:
            os.unlink(p)
        raise


def store_verified_local_backup(
        path, *, encrypted_archive, recovery_key, trusted_public_keys,
        approve_new_backup=False, windows_storage_reviewed=False):
    """Verify signed history then exclusively save ciphertext, never a key.

    The approving operator must already know the chosen directory is PRIVATE.
    No overwrite, zero unencrypted temporary files, no auto-backups to cloud.
    """
    if approve_new_backup is not True:
        raise ValueError("explicit new backup approval required")
    p = _checked_location(
        path, windows_storage_reviewed=windows_storage_reviewed)
    cycles = _verify(
        encrypted_archive, recovery_key=recovery_key,
        trusted_public_keys=trusted_public_keys)
    _create_once(p, encrypted_archive)
    return {
        'encrypted_file_created': True,
        'signed_review_cycles_verified': cycles,
        'plaintext_or_key_files_written': False,
        'external_api_calls': 0,
        'backup_device_separation_verified_by_code': False,
    }


def read_verified_local_backup(
        path, *, recovery_key, trusted_public_keys,
        windows_storage_reviewed=False):
    """Read an existing owner-only ciphertext file and verify signatures."""
    p = _checked_location(
        path, windows_storage_reviewed=windows_storage_reviewed)
    info = p.lstat()
    if (not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or (hasattr(info, 'st_file_attributes')
                and info.st_file_attributes & _REPARSE)
            or not 1 <= info.st_size <= MAX_RECOVERY_ARCHIVE_BYTES):
        raise PermissionError("unsafe or oversized backup file")
    if (os.name == "posix"
            and (info.st_uid != os.getuid()
                 or stat.S_IMODE(info.st_mode) != 0o600)):
        raise PermissionError("backup file must be owner-only 0600")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_BINARY", 0)
    fd = os.open(str(p), flags)
    try:
        after = os.fstat(fd)
        if (not stat.S_ISREG(after.st_mode)
                or after.st_dev != info.st_dev
                or after.st_ino != info.st_ino
                or not 1 <= after.st_size <= MAX_RECOVERY_ARCHIVE_BYTES):
            raise PermissionError("backup changed while being opened")
        with os.fdopen(fd, 'rb') as stream:
            fd = -1
            archive = stream.read(MAX_RECOVERY_ARCHIVE_BYTES + 1)
    finally:
        if fd != -1:
            os.close(fd)
    cycles = _verify(
        archive, recovery_key=recovery_key,
        trusted_public_keys=trusted_public_keys)
    return {
        'private_encrypted_archive': archive,
        'summary': {
            'encrypted_backup_verified': True,
            'signed_review_cycles_verified': cycles,
            'files_or_keys_written': False,
            'external_api_calls': 0,
        },
    }


def copy_backup_to_separate_location(
        source_path, destination_path, *, recovery_key, trusted_public_keys,
        approve_independent_copy=False, operator_confirmed_separate_device=False,
        windows_storage_reviewed=False):
    """Verify then copy encrypted bytes to a second, distinct chosen directory.

    The operator MUST verify physical/storage independence externally; merely
    different directory names do NOT prove separation. No USB/cloud detection.
    """
    if (approve_independent_copy is not True
            or operator_confirmed_separate_device is not True):
        raise ValueError("separate backup device requires explicit confirmation")
    source = _checked_location(
        source_path, windows_storage_reviewed=windows_storage_reviewed)
    destination = _checked_location(
        destination_path, windows_storage_reviewed=windows_storage_reviewed)
    if source.parent == destination.parent:
        raise ValueError("backup copies cannot share a folder")
    verified = read_verified_local_backup(
        source, recovery_key=recovery_key,
        trusted_public_keys=trusted_public_keys,
        windows_storage_reviewed=windows_storage_reviewed)
    _create_once(destination, verified['private_encrypted_archive'])
    return {
        'independent_copy_created': True,
        'separate_device_confirmed_by_operator': True,
        'physical_storage_independence_verified_by_code': False,
        'signed_review_cycles_verified':
            verified['summary']['signed_review_cycles_verified'],
        'plaintext_or_keys_written': False,
        'external_api_calls': 0,
    }
