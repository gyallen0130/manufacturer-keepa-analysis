"""Private inventory persistence tests; only fake file IDs and ephemeral keys."""
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from cryptography.fernet import Fernet
from supplier_docs.snapshot_store import (
    finalize_inventory, read_encrypted_inventory, review_queue,
    write_encrypted_inventory,
)
from supplier_docs.drive_delta import SCHEMA_VERSION

FOLDER = 'fake_folder_987654'
FILE_A = 'fake_sheet_abcdefgh12'
FILE_B = 'fake_binary_abcd34'
FILE_C = 'fake_sheet_new12345'
SHEETS = 'application/vnd.google-apps.spreadsheet'
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def sample(files):
    return {FOLDER: {
        'schema_version': SCHEMA_VERSION,
        'folder_id': FOLDER,
        'files': {file_id: {
            'mime_type': mime, 'version': version, 'modified_time': ''}
            for file_id, (mime, version) in files.items()},
        'total_items': len(files), 'pages_scanned': 1,
        'unsupported_items': 0, 'unscanned_subfolders': 0,
    }}


class PrivateInventoryTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.folder.chmod(0o700)
        self.file = self.folder / 'inventory.enc'
        self.key = Fernet.generate_key()
        self.before = sample({FILE_A: (SHEETS, '1')})
        self.after = sample({
            FILE_A: (SHEETS, '2'), FILE_B: (XLSX, '1')})

    def test_baseline_must_be_explicitly_approved(self):
        with self.assertRaises(ValueError):
            finalize_inventory(None, self.before)
        approved = finalize_inventory(
            None, self.before, approve_initial_baseline=True)
        revision = write_encrypted_inventory(
            self.file, key=self.key, snapshots=approved)
        self.assertEqual(len(revision), 64)
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)
        encrypted = self.file.read_bytes()
        self.assertNotIn(FILE_A.encode(), encrypted)
        result, disk_revision = read_encrypted_inventory(
            self.file, key=self.key)
        self.assertEqual(result, approved)
        self.assertEqual(revision, disk_revision)

    def test_failure_or_unapproved_file_blocks_baseline_advance(self):
        with self.assertRaises(ValueError):
            finalize_inventory(self.before, self.after)
        with self.assertRaises(ValueError):
            finalize_inventory(self.before, self.after,
                               completed_locations=[(FOLDER, FILE_A)])
        done = [(FOLDER, FILE_A), (FOLDER, FILE_B)]
        with self.assertRaises(ValueError):
            finalize_inventory(
                self.before, self.after,
                completed_locations=done + [done[0]])
        self.assertEqual(finalize_inventory(
            self.before, self.after, completed_locations=done), self.after)

    def test_missing_file_requires_separate_review_not_deletion(self):
        new = sample({})
        with self.assertRaises(ValueError):
            finalize_inventory(self.before, new)
        current = finalize_inventory(
            self.before, new, reviewed_unavailable=[(FOLDER, FILE_A)])
        self.assertEqual(current, new)
        with self.assertRaises(ValueError):
            finalize_inventory(
                self.before, new,
                reviewed_unavailable=[(FOLDER, FILE_B)])

    def test_queue_only_contains_changed_files_with_safe_type_routing(self):
        queue = review_queue(self.before, self.after)
        self.assertEqual(len(queue['private_queue']), 2)
        statuses = {item['file_id']: item['status']
                    for item in queue['private_queue']}
        self.assertEqual(statuses[FILE_A], 'sheets_review_required')
        self.assertEqual(statuses[FILE_B], 'unsupported_download_review_required')
        summary = json.dumps(queue['summary'])
        for secret in (FILE_A, FILE_B, FOLDER):
            self.assertNotIn(secret, summary)
        self.assertNotIn('modified_time', json.dumps(queue['summary']))

    def test_revision_guard_and_ciphertext_tampering(self):
        old_revision = write_encrypted_inventory(
            self.file, key=self.key, snapshots=self.before)
        with self.assertRaises(FileExistsError):
            write_encrypted_inventory(
                self.file, key=self.key, snapshots=self.after)
        next_revision = write_encrypted_inventory(
            self.file, key=self.key, snapshots=self.after,
            expected_revision=old_revision)
        self.assertNotEqual(next_revision, old_revision)
        with self.assertRaises(ValueError):
            write_encrypted_inventory(
                self.file, key=self.key, snapshots=self.after,
                expected_revision=old_revision)
        data = self.file.read_bytes()
        self.file.write_bytes(data[:-4] + b'XXXX')
        with self.assertRaises(ValueError):
            read_encrypted_inventory(self.file, key=self.key)

    def test_wrong_key_and_missing_state_fail_closed(self):
        with self.assertRaises(FileNotFoundError):
            read_encrypted_inventory(self.file, key=self.key)
        write_encrypted_inventory(
            self.file, key=self.key, snapshots=self.before)
        with self.assertRaises(ValueError):
            read_encrypted_inventory(self.file, key=Fernet.generate_key())
        with self.assertRaises(ValueError):
            read_encrypted_inventory(self.file, key=b'not-a-valid-key')

    def test_world_readable_file_or_directory_is_rejected(self):
        write_encrypted_inventory(
            self.file, key=self.key, snapshots=self.before)
        self.file.chmod(0o644)
        with self.assertRaises(PermissionError):
            read_encrypted_inventory(self.file, key=self.key)
        self.file.chmod(0o600)
        self.folder.chmod(0o755)
        with self.assertRaises(PermissionError):
            read_encrypted_inventory(self.file, key=self.key)
        with self.assertRaises(PermissionError):
            write_encrypted_inventory(
                self.file, key=self.key, snapshots=self.after)

    def test_symlink_baseline_is_rejected(self):
        target = self.folder / 'real.enc'
        target.write_bytes(b'not-secret')
        target.chmod(0o600)
        self.file.symlink_to(target)
        with self.assertRaises(PermissionError):
            read_encrypted_inventory(self.file, key=self.key)
        with self.assertRaises(PermissionError):
            write_encrypted_inventory(
                self.file, key=self.key, snapshots=self.before)

    def test_invalid_snapshot_does_not_create_file(self):
        bad = sample({FILE_A: (SHEETS, '')})
        with self.assertRaises(ValueError):
            write_encrypted_inventory(
                self.file, key=self.key, snapshots=bad)
        self.assertFalse(self.file.exists())

    def test_inaccessible_folder_set_change_blocks_commit(self):
        different = sample({})
        different['different_folder_123'] = different.pop(FOLDER)
        different['different_folder_123']['folder_id'] = 'different_folder_123'
        with self.assertRaises(ValueError):
            finalize_inventory(self.before, different)

    def test_no_unrequested_remote_activity(self):
        approved = finalize_inventory(
            None, self.before, approve_initial_baseline=True)
        write_encrypted_inventory(
            self.file, key=self.key, snapshots=approved)
        self.assertTrue(self.file.exists())
        self.assertFalse((self.folder / 'credentials.json').exists())


if __name__ == '__main__':
    unittest.main()
