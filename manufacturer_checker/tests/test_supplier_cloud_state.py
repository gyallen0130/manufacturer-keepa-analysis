"""Offline GCS generation-CAS tests. No Google credentials or network calls."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import unittest

from cryptography.fernet import Fernet
from supplier_docs.cloud_state import (
    read_cloud_inventory, write_cloud_inventory,
    read_cloud_review_journal, write_cloud_review_journal,
)
from supplier_docs.drive_delta import SCHEMA_VERSION
from supplier_docs.review_gate import issue_review_receipt

FOLDER = 'fake_folder_abcdef123'
FILE = 'fake_sheet_abcdef123'
MIME = 'application/vnd.google-apps.spreadsheet'
SIGN_KEY = b'unit-tests-dedicated-review-signing-key-123456789'
ACTORS = {'actor_test_1'}
TIME = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)


def inventory(version):
    return {FOLDER: {
        'schema_version': SCHEMA_VERSION, 'folder_id': FOLDER,
        'files': {FILE: {
            'mime_type': MIME, 'version': version, 'modified_time': ''}},
        'total_items': 1, 'pages_scanned': 1,
        'unsupported_items': 0, 'unscanned_subfolders': 0,
    }}


class FakeBlob:
    """Models GCS's conditional writes without a real client."""
    def __init__(self, name, bucket='supplier-docs-state-test-example'):
        self.name = name
        self.bucket = SimpleNamespace(name=bucket)
        self._payload = None
        self._generation = None
        self.generation = None
        self.size = None
        self.uploads = 0
        self.reads = 0

    def reload(self, timeout):
        if self._payload is None:
            raise FileNotFoundError('no object')
        self.generation = self._generation
        self.size = len(self._payload)

    def download_as_bytes(self, *, if_generation_match, timeout):
        if self._payload is None or self._generation != if_generation_match:
            raise RuntimeError('412 generation mismatch')
        self.reads += 1
        return self._payload

    def upload_from_string(self, data, *, content_type,
                           if_generation_match, timeout):
        if self._payload is None:
            if if_generation_match != 0:
                raise RuntimeError('412 missing object')
            self._generation = 1
        else:
            if if_generation_match != self._generation:
                raise RuntimeError('412 generation mismatch')
            self._generation += 1
        self._payload = bytes(data)
        self.uploads += 1
        self.generation = self._generation
        self.size = len(self._payload)


class CloudStateTests(unittest.TestCase):
    def setUp(self):
        self.key = Fernet.generate_key()
        self.inventory_blob = FakeBlob('supplier-docs/inventory.enc')
        self.journal_blob = FakeBlob('supplier-docs/review-journal.enc')
        self.before = inventory('1')
        self.current = inventory('2')
        self.receipt = issue_review_receipt(
            self.before, self.current,
            folder_id=FOLDER, file_id=FILE, event='changed',
            reviewer_id='actor_test_1', evidence_ref='evidence_123456',
            signing_key=SIGN_KEY, reviewed_at=TIME)

    def test_create_then_read_then_cas_update_inventory(self):
        result = write_cloud_inventory(
            self.inventory_blob, cipher_key=self.key,
            approved_snapshots=self.before, expected_generation=0)
        self.assertTrue(result['generation_precondition_used'])
        self.assertNotIn(FILE.encode(), self.inventory_blob._payload)
        before, g1 = read_cloud_inventory(
            self.inventory_blob, cipher_key=self.key)
        self.assertEqual(before, self.before)
        self.assertEqual(g1, 1)
        write_cloud_inventory(
            self.inventory_blob, cipher_key=self.key,
            approved_snapshots=self.current, expected_generation=g1)
        after, g2 = read_cloud_inventory(
            self.inventory_blob, cipher_key=self.key)
        self.assertEqual(after, self.current)
        self.assertEqual(g2, 2)

    def test_creating_twice_and_stale_generation_fail(self):
        write_cloud_inventory(
            self.inventory_blob, cipher_key=self.key,
            approved_snapshots=self.before, expected_generation=0)
        with self.assertRaises(RuntimeError):
            write_cloud_inventory(
                self.inventory_blob, cipher_key=self.key,
                approved_snapshots=self.before, expected_generation=0)
        with self.assertRaises(RuntimeError):
            write_cloud_inventory(
                self.inventory_blob, cipher_key=self.key,
                approved_snapshots=self.current, expected_generation=999)
        self.assertEqual(self.inventory_blob.uploads, 1)

    def test_missing_baseline_rejected(self):
        with self.assertRaises(FileNotFoundError):
            read_cloud_inventory(self.inventory_blob, cipher_key=self.key)

    def test_wrong_key_and_tampering_fail(self):
        write_cloud_inventory(
            self.inventory_blob, cipher_key=self.key,
            approved_snapshots=self.before, expected_generation=0)
        with self.assertRaises(ValueError):
            read_cloud_inventory(
                self.inventory_blob, cipher_key=Fernet.generate_key())
        self.inventory_blob._payload = b'corrupted-ciphertext'
        with self.assertRaises(ValueError):
            read_cloud_inventory(self.inventory_blob, cipher_key=self.key)

    def test_bucket_and_object_names_cannot_target_spapi_storage(self):
        for blob in [
            FakeBlob('supplier-docs/inventory.enc',
                     bucket='amazon-spapi-production-data'),
            FakeBlob('amazon-spapi/private.enc'),
            FakeBlob('supplier-docs/review-journal.enc'),
        ]:
            with self.subTest(blob=blob.name), self.assertRaises(ValueError):
                write_cloud_inventory(
                    blob, cipher_key=self.key, approved_snapshots=self.before,
                    expected_generation=0)
            self.assertEqual(blob.uploads, 0)

    def test_invalid_generation_and_state_fail_before_write(self):
        for value in (-1, None, '1', True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                write_cloud_inventory(
                    self.inventory_blob, cipher_key=self.key,
                    approved_snapshots=self.before, expected_generation=value)
        with self.assertRaises(ValueError):
            write_cloud_inventory(
                self.inventory_blob, cipher_key=self.key,
                approved_snapshots=inventory(''),
                expected_generation=0)
        self.assertEqual(self.inventory_blob.uploads, 0)

    def test_review_receipt_journal_create_read_and_reject_deletion(self):
        write_cloud_review_journal(
            self.journal_blob, cipher_key=self.key, signing_key=SIGN_KEY,
            previous=self.before, current=self.current,
            receipts=[self.receipt], allowed_reviewers=ACTORS,
            expected_generation=0)
        result, gen = read_cloud_review_journal(
            self.journal_blob, cipher_key=self.key, signing_key=SIGN_KEY,
            previous=self.before, current=self.current,
            allowed_reviewers=ACTORS)
        self.assertEqual(result, [self.receipt])
        self.assertEqual(gen, 1)
        self.assertNotIn(FILE.encode(), self.journal_blob._payload)
        with self.assertRaises(ValueError):
            write_cloud_review_journal(
                self.journal_blob, cipher_key=self.key, signing_key=SIGN_KEY,
                previous=self.before, current=self.current,
                receipts=[], allowed_reviewers=ACTORS,
                expected_generation=gen)
        self.assertEqual(self.journal_blob.uploads, 1)

    def test_review_cannot_reuse_old_inventory_context(self):
        write_cloud_review_journal(
            self.journal_blob, cipher_key=self.key, signing_key=SIGN_KEY,
            previous=self.before, current=self.current,
            receipts=[self.receipt], allowed_reviewers=ACTORS,
            expected_generation=0)
        with self.assertRaises(ValueError):
            read_cloud_review_journal(
                self.journal_blob, cipher_key=self.key, signing_key=SIGN_KEY,
                previous=self.before, current=inventory('3'),
                allowed_reviewers=ACTORS)

    def test_review_signing_secret_must_be_separate(self):
        with self.assertRaises(ValueError):
            write_cloud_review_journal(
                self.journal_blob, cipher_key=self.key, signing_key=self.key,
                previous=self.before, current=self.current,
                receipts=[], allowed_reviewers=ACTORS,
                expected_generation=0)
        self.assertEqual(self.journal_blob.uploads, 0)

    def test_review_stale_generation_is_rejected(self):
        write_cloud_review_journal(
            self.journal_blob, cipher_key=self.key, signing_key=SIGN_KEY,
            previous=self.before, current=self.current,
            receipts=[self.receipt], allowed_reviewers=ACTORS,
            expected_generation=0)
        with self.assertRaises(ValueError):
            write_cloud_review_journal(
                self.journal_blob, cipher_key=self.key, signing_key=SIGN_KEY,
                previous=self.before, current=self.current,
                receipts=[self.receipt], allowed_reviewers=ACTORS,
                expected_generation=5)
        self.assertEqual(self.journal_blob.uploads, 1)


if __name__ == '__main__':
    unittest.main()
