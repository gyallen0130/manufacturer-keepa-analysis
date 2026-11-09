"""Offline encrypted review journal tests; no real files, users, secrets or IDs."""
from datetime import datetime, timezone
import os
from pathlib import Path
import stat
import tempfile
import unittest

from cryptography.fernet import Fernet
from supplier_docs.drive_delta import SCHEMA_VERSION
from supplier_docs.review_gate import issue_review_receipt, plan_review_retries
from supplier_docs.review_journal import (
    read_encrypted_review_journal, write_encrypted_review_journal,
)

FOLDER = 'fake_folder_abcdef123'
DOC = 'fake_sheet_abcdef123'
OTHER = 'fake_sheet_ghijkl456'
NATIVE = 'application/vnd.google-apps.spreadsheet'
SIGN_KEY = b'fake-signing-key-for-unit-tests-0123456789'
ACTORS = {'actor_test_1'}
TIME = datetime(2026, 1, 1, 10, 5, tzinfo=timezone.utc)


def snapshot(versions):
    return {FOLDER: {'schema_version': SCHEMA_VERSION, 'folder_id': FOLDER,
                     'files': {file_id: {'mime_type': NATIVE, 'version': ver,
                                         'modified_time': ''}
                               for file_id, ver in versions.items()},
                     'total_items': len(versions), 'pages_scanned': 1,
                     'unsupported_items': 0, 'unscanned_subfolders': 0}}


class EncryptedReviewJournalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.root.chmod(0o700)
        self.path = self.root / 'review.enc'
        self.key = Fernet.generate_key()
        self.before = snapshot({DOC: '1'})
        self.current = snapshot({DOC: '2', OTHER: '1'})
        self.first = self.make_receipt(DOC)
        self.second = self.make_receipt(OTHER)

    def make_receipt(self, file_id):
        return issue_review_receipt(
            self.before, self.current,
            folder_id=FOLDER, file_id=file_id, event='changed',
            reviewer_id='actor_test_1', evidence_ref='evidence_123456',
            signing_key=SIGN_KEY, reviewed_at=TIME)

    def write(self, receipts, **changes):
        return write_encrypted_review_journal(
            self.path, cipher_key=self.key, signing_key=SIGN_KEY,
            previous=self.before, current=self.current,
            receipts=receipts, allowed_reviewers=ACTORS, **changes)

    def read(self, **changes):
        return read_encrypted_review_journal(
            self.path, cipher_key=self.key, signing_key=SIGN_KEY,
            previous=self.before, current=self.current,
            allowed_reviewers=ACTORS, **changes)

    def test_private_creation_and_restartable_append(self):
        rev1 = self.write([self.first])
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertNotIn(DOC.encode(), self.path.read_bytes())
        journal, seen_revision = self.read()
        self.assertEqual(journal, [self.first])
        self.assertEqual(rev1, seen_revision)
        plan = plan_review_retries(
            self.before, self.current, receipts=journal,
            signing_key=SIGN_KEY, allowed_reviewers=ACTORS)
        self.assertEqual(plan['summary']['retry_pending'], 1)
        rev2 = self.write([self.first, self.second], expected_revision=rev1)
        self.assertNotEqual(rev1, rev2)
        journal2, _ = self.read()
        self.assertEqual(len(journal2), 2)
        self.assertTrue(plan_review_retries(
            self.before, self.current, receipts=journal2,
            signing_key=SIGN_KEY,
            allowed_reviewers=ACTORS)['summary']['ready_to_finalize'])

    def test_no_overwrite_without_revision_and_no_removal(self):
        rev1 = self.write([self.first])
        with self.assertRaises(FileExistsError):
            self.write([self.first, self.second])
        with self.assertRaises(ValueError):
            self.write([], expected_revision=rev1)
        with self.assertRaises(ValueError):
            self.write([self.second], expected_revision=rev1)
        self.assertEqual(self.read()[0], [self.first])

    def test_stale_revision_rejected_without_modifying_file(self):
        rev1 = self.write([self.first])
        rev2 = self.write([self.first, self.second], expected_revision=rev1)
        data = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.write([self.first, self.second], expected_revision=rev1)
        self.assertEqual(self.path.read_bytes(), data)
        self.assertEqual(self.read()[1], rev2)

    def test_changed_source_revision_cannot_reuse_old_approvals(self):
        self.write([self.first])
        newer = snapshot({DOC: '3', OTHER: '1'})
        with self.assertRaises(ValueError):
            read_encrypted_review_journal(
                self.path, cipher_key=self.key, signing_key=SIGN_KEY,
                previous=self.before, current=newer,
                allowed_reviewers=ACTORS)

    def test_wrong_encryption_key_tampering_or_signature_blocked(self):
        self.write([self.first])
        with self.assertRaises(ValueError):
            read_encrypted_review_journal(
                self.path, cipher_key=Fernet.generate_key(), signing_key=SIGN_KEY,
                previous=self.before, current=self.current,
                allowed_reviewers=ACTORS)
        data = self.path.read_bytes()
        self.path.write_bytes(data[:-6] + b'XXXXXX')
        with self.assertRaises(ValueError):
            self.read()

    def test_untrusted_record_rejected_before_disk_write(self):
        fake = {**self.first, 'reviewer_id': 'another_actor'}
        with self.assertRaises(ValueError):
            self.write([fake])
        self.assertFalse(self.path.exists())
        with self.assertRaises(ValueError):
            write_encrypted_review_journal(
                self.path, cipher_key=SIGN_KEY, signing_key=SIGN_KEY,
                previous=self.before, current=self.current,
                receipts=[self.first], allowed_reviewers=ACTORS)
        self.assertFalse(self.path.exists())

    def test_permissions_and_symlink_defenses(self):
        self.write([self.first])
        self.path.chmod(0o644)
        with self.assertRaises(PermissionError):
            self.read()
        self.path.chmod(0o600)
        self.root.chmod(0o755)
        with self.assertRaises(PermissionError):
            self.read()
        with self.assertRaises(PermissionError):
            self.write([self.first])
        self.root.chmod(0o700)
        self.path.unlink()
        target = self.root / 'protected.enc'
        target.write_bytes(b'faked')
        target.chmod(0o600)
        self.path.symlink_to(target)
        with self.assertRaises(PermissionError):
            self.read()

    def test_missing_journal_is_not_implicit_success(self):
        with self.assertRaises(FileNotFoundError):
            self.read()

    def test_signature_revision_mismatch_after_context_switch(self):
        self.write([self.first])
        other_previous = snapshot({DOC: '0'})
        with self.assertRaises(ValueError):
            read_encrypted_review_journal(
                self.path, cipher_key=self.key, signing_key=SIGN_KEY,
                previous=other_previous, current=self.current,
                allowed_reviewers=ACTORS)


if __name__ == '__main__':
    unittest.main()
