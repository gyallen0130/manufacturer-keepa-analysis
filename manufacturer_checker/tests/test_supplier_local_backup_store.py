"""No-network temporary-directory tests for Windows/Colab local backup design."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from supplier_docs.drive_delta import SCHEMA_VERSION
from supplier_docs.offline_review import issue_offline_ed25519_receipt
from supplier_docs.private_audit_bundle import (
    initialize_audit_bundle, propose_next_audit_bundle,
)
from supplier_docs.offline_recovery_archive import (
    create_offline_recovery_archive, _github_blob_sha,
)
from supplier_docs.local_backup_store import (
    store_verified_local_backup, read_verified_local_backup,
    copy_backup_to_separate_location,
)

FOLDER = 'fake_folder_localabc123'
SHEET = 'fake_sheet_localxyz123'
MIME = 'application/vnd.google-apps.spreadsheet'
REVIEWER = 'fake_local_reviewer_123'


def state(version):
    return {FOLDER: {
        'schema_version': SCHEMA_VERSION, 'folder_id': FOLDER,
        'files': {SHEET: {
            'mime_type': MIME, 'version': version,
            'modified_time': ''}},
        'total_items': 1, 'pages_scanned': 1,
        'unsupported_items': 0, 'unscanned_subfolders': 0,
    }}


class LocalBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.one = Path(self.tmp.name, 'main')
        self.two = Path(self.tmp.name, 'second')
        self.one.mkdir(mode=0o700)
        self.two.mkdir(mode=0o700)
        if os.name == 'posix':
            os.chmod(self.one, 0o700)
            os.chmod(self.two, 0o700)
        self.path = self.one / 'signed-review-backup.enc'
        self.copy_path = self.two / 'signed-review-backup.enc'
        self.primary_key = Fernet.generate_key()
        self.recovery_key = Fernet.generate_key()
        reviewer_key = Ed25519PrivateKey.generate()
        self.trusted = {REVIEWER: reviewer_key.public_key()}
        old, updated = state('1'), state('2')
        receipt = issue_offline_ed25519_receipt(
            old, updated, folder_id=FOLDER, file_id=SHEET, event='changed',
            reviewer_id=REVIEWER, evidence_ref='fake_evidence_local1234',
            private_key=reviewer_key,
            reviewed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        bundle = propose_next_audit_bundle(
            initialize_audit_bundle(old, approve_initial_baseline=True),
            updated, receipts=[receipt], trusted_public_keys=self.trusted)
        encrypted = Fernet(self.primary_key).encrypt(
            json.dumps(bundle).encode())
        self.backup = create_offline_recovery_archive(
            encrypted, primary_key=self.primary_key,
            recovery_key=self.recovery_key,
            source_blob_sha=_github_blob_sha(encrypted),
            trusted_public_keys=self.trusted)['private_encrypted_archive']

    def save(self, **extra):
        cfg = {
            'path': self.path, 'encrypted_archive': self.backup,
            'recovery_key': self.recovery_key,
            'trusted_public_keys': self.trusted,
            'approve_new_backup': True,
            'windows_storage_reviewed': True,
        }
        cfg.update(extra)
        return store_verified_local_backup(**cfg)

    def read(self, **extra):
        cfg = {
            'path': self.path, 'recovery_key': self.recovery_key,
            'trusted_public_keys': self.trusted,
            'windows_storage_reviewed': True,
        }
        cfg.update(extra)
        return read_verified_local_backup(**cfg)

    def copy(self, **extra):
        cfg = {
            'source_path': self.path, 'destination_path': self.copy_path,
            'recovery_key': self.recovery_key,
            'trusted_public_keys': self.trusted,
            'approve_independent_copy': True,
            'operator_confirmed_separate_device': True,
            'windows_storage_reviewed': True,
        }
        cfg.update(extra)
        return copy_backup_to_separate_location(**cfg)

    def test_encrypted_archive_create_once_and_read_verified(self):
        created = self.save()
        self.assertTrue(created['encrypted_file_created'])
        self.assertFalse(created['plaintext_or_key_files_written'])
        self.assertEqual(created['signed_review_cycles_verified'], 1)
        self.assertEqual(self.path.read_bytes(), self.backup)
        self.assertNotIn(SHEET.encode(), self.path.read_bytes())
        result = self.read()
        self.assertEqual(result['private_encrypted_archive'], self.backup)
        self.assertEqual(result['summary']['signed_review_cycles_verified'], 1)
        self.assertFalse(result['summary']['files_or_keys_written'])
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_explicit_approval_required_before_any_file_creation(self):
        with self.assertRaises(ValueError):
            self.save(approve_new_backup=False)
        with self.assertRaises(ValueError):
            self.save(approve_new_backup=1)
        self.assertFalse(self.path.exists())

    def test_never_overwrite_existing_backup(self):
        self.save()
        first = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            self.save()
        self.assertEqual(first, self.path.read_bytes())

    def test_wrong_key_and_tampered_archive_are_rejected(self):
        with self.assertRaises(ValueError):
            self.save(recovery_key=Fernet.generate_key())
        with self.assertRaises(ValueError):
            self.save(encrypted_archive=self.backup[:-4] + b'ABCD')
        self.assertFalse(self.path.exists())
        self.save()
        self.path.write_bytes(b'corrupted-data')
        with self.assertRaises(ValueError):
            self.read()

    def test_other_reviewer_key_is_rejected_before_storage(self):
        other = {REVIEWER: Ed25519PrivateKey.generate().public_key()}
        with self.assertRaises(ValueError):
            self.save(trusted_public_keys=other)
        self.assertFalse(self.path.exists())

    def test_missing_directory_and_relative_destination_are_rejected(self):
        with self.assertRaises(ValueError):
            self.save(path='relative-file.enc')
        with self.assertRaises(ValueError):
            self.save(path=self.one / 'missing' / 'backup.enc')
        self.assertFalse(self.path.exists())

    @unittest.skipUnless(os.name == 'posix', '0700 permissions apply only to POSIX')
    def test_parent_permissions_and_file_permissions_must_be_private(self):
        os.chmod(self.one, 0o755)
        with self.assertRaises(PermissionError):
            self.save()
        os.chmod(self.one, 0o700)
        self.save()
        os.chmod(self.path, 0o644)
        with self.assertRaises(PermissionError):
            self.read()

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink control test')
    def test_symlink_parent_and_destination_rejected(self):
        self.save()
        shortcut = Path(self.tmp.name, 'alias')
        shortcut.symlink_to(self.one, target_is_directory=True)
        with self.assertRaises(PermissionError):
            self.read(path=shortcut / self.path.name)
        link = self.two / 'link.enc'
        link.symlink_to(self.path)
        with self.assertRaises(FileExistsError):
            self.save(path=link)

    def test_separate_copy_requires_explicit_operator_custody_review(self):
        self.save()
        for config in [
            {'approve_independent_copy': False},
            {'operator_confirmed_separate_device': False},
            {'operator_confirmed_separate_device': 1},
        ]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                self.copy(**config)
        self.assertFalse(self.copy_path.exists())

    def test_independent_copy_checks_archive_and_never_overwrites(self):
        self.save()
        report = self.copy()
        self.assertTrue(report['independent_copy_created'])
        self.assertFalse(report['physical_storage_independence_verified_by_code'])
        self.assertTrue(report['separate_device_confirmed_by_operator'])
        self.assertEqual(self.copy_path.read_bytes(), self.path.read_bytes())
        with self.assertRaises(FileExistsError):
            self.copy()

    def test_copy_within_same_folder_is_rejected(self):
        self.save()
        with self.assertRaises(ValueError):
            self.copy(destination_path=self.one / 'second.enc')

    def test_copy_fails_if_source_was_corrupted(self):
        self.save()
        self.path.write_bytes(b'broken')
        with self.assertRaises(ValueError):
            self.copy()
        self.assertFalse(self.copy_path.exists())


if __name__ == '__main__':
    unittest.main()
