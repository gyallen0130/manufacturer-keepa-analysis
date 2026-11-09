"""Synthetic offline recovery: no GitHub credentials, real keys, network or files."""
from datetime import datetime, timezone
import hashlib
import json
import unittest

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from supplier_docs.drive_delta import SCHEMA_VERSION
from supplier_docs.offline_review import issue_offline_ed25519_receipt
from supplier_docs.private_audit_bundle import (
    initialize_audit_bundle, propose_next_audit_bundle,
    verify_audit_bundle,
)
from supplier_docs.offline_recovery_archive import (
    create_offline_recovery_archive,
    inspect_offline_recovery_archive,
    prepare_offline_recovery_ciphertext,
)

FOLDER = 'fake_folder_backupabc123'
SHEET = 'fake_sheet_backupxyz123'
MIME = 'application/vnd.google-apps.spreadsheet'
WHO = 'fake_backup_reviewer1'
TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def state(version):
    return {FOLDER: {
        'schema_version': SCHEMA_VERSION, 'folder_id': FOLDER,
        'files': {SHEET: {
            'mime_type': MIME, 'version': version,
            'modified_time': ''}},
        'total_items': 1, 'pages_scanned': 1,
        'unsupported_items': 0, 'unscanned_subfolders': 0,
    }}


def git_blob_sha(cipher):
    return hashlib.sha1(
        b'blob ' + str(len(cipher)).encode() + b'\0' + cipher).hexdigest()


class OfflineRecoveryArchiveTests(unittest.TestCase):
    def setUp(self):
        self.primary = Fernet.generate_key()
        self.recovery = Fernet.generate_key()
        self.signer = Ed25519PrivateKey.generate()
        self.public = {WHO: self.signer.public_key()}
        start, changed = state('1'), state('2')
        receipt = issue_offline_ed25519_receipt(
            start, changed, folder_id=FOLDER, file_id=SHEET,
            event='changed', reviewer_id=WHO,
            evidence_ref='fake_evidence_backup123',
            private_key=self.signer, reviewed_at=TIME)
        initial = initialize_audit_bundle(
            start, approve_initial_baseline=True)
        self.bundle = propose_next_audit_bundle(
            initial, changed, receipts=[receipt],
            trusted_public_keys=self.public)
        self.cipher = Fernet(self.primary).encrypt(
            json.dumps(self.bundle, sort_keys=True, separators=(',', ':')).encode())
        self.sha = git_blob_sha(self.cipher)

    def export(self, **kw):
        params = dict(
            encrypted_checkpoint=self.cipher,
            primary_key=self.primary,
            recovery_key=self.recovery,
            source_blob_sha=self.sha,
            trusted_public_keys=self.public)
        params.update(kw)
        return create_offline_recovery_archive(**params)

    def test_backup_has_no_plaintext_ids_and_no_disk_writes(self):
        result = self.export()
        sealed = result['private_encrypted_archive']
        self.assertIsInstance(sealed, bytes)
        self.assertNotIn(FOLDER.encode(), sealed)
        self.assertNotIn(SHEET.encode(), sealed)
        self.assertNotIn(WHO.encode(), sealed)
        self.assertNotIn(self.primary, sealed)
        self.assertNotIn(self.recovery, sealed)
        self.assertFalse(result['summary']['remote_or_local_files_written'])
        self.assertFalse(result['summary']['restore_approved'])
        self.assertEqual(result['summary']['review_cycles_verified'], 1)

    def test_restore_with_recovery_key_and_new_primary_keeps_history(self):
        sealed = self.export()['private_encrypted_archive']
        new_key = Fernet.generate_key()
        prepared = prepare_offline_recovery_ciphertext(
            sealed, recovery_key=self.recovery,
            new_primary_key=new_key, trusted_public_keys=self.public,
            approve_offline_recovery=True)
        restored = json.loads(Fernet(new_key).decrypt(
            prepared['private_reencrypted_checkpoint']))
        self.assertEqual(restored, self.bundle)
        self.assertEqual(prepared['private_source_blob_sha'], self.sha)
        self.assertFalse(prepared['summary']['remote_write_performed'])
        self.assertTrue(
            prepared['summary']['remote_generation_recheck_required'])
        verify_audit_bundle(restored, trusted_public_keys=self.public)

    def test_recovery_requires_conscious_manual_approval(self):
        sealed = self.export()['private_encrypted_archive']
        with self.assertRaises(ValueError):
            prepare_offline_recovery_ciphertext(
                sealed, recovery_key=self.recovery,
                new_primary_key=Fernet.generate_key(),
                trusted_public_keys=self.public)
        with self.assertRaises(ValueError):
            prepare_offline_recovery_ciphertext(
                sealed, recovery_key=self.recovery,
                new_primary_key=Fernet.generate_key(),
                trusted_public_keys=self.public,
                approve_offline_recovery=1)

    def test_primary_and_recovery_key_must_be_distinct(self):
        with self.assertRaises(ValueError):
            self.export(recovery_key=self.primary)
        with self.assertRaises(ValueError):
            self.export(primary_key=b'not-a-valid-key')

    def test_wrong_backup_key_and_tampering_rejected(self):
        sealed = self.export()['private_encrypted_archive']
        for archive, key in (
            (sealed, Fernet.generate_key()),
            (sealed[:-4] + b'AAAA', self.recovery),
            (b'broken', self.recovery),
        ):
            with self.subTest(archive=archive[:12]), self.assertRaises(ValueError):
                inspect_offline_recovery_archive(
                    archive, recovery_key=key,
                    trusted_public_keys=self.public)

    def test_source_sha_must_match_ciphertext_exactly(self):
        with self.assertRaises(ValueError):
            self.export(source_blob_sha='0' * 40)
        with self.assertRaises(ValueError):
            self.export(encrypted_checkpoint=self.cipher + b'X')

    def test_invalid_or_changed_reviewer_public_key_rejected(self):
        sealed = self.export()['private_encrypted_archive']
        for keyring in (
            {}, {WHO: Ed25519PrivateKey.generate().public_key()},
        ):
            with self.subTest(keyring=bool(keyring)), self.assertRaises(ValueError):
                inspect_offline_recovery_archive(
                    sealed, recovery_key=self.recovery,
                    trusted_public_keys=keyring)

    def test_forged_signed_history_rejected_before_backup(self):
        forged = {**self.bundle, 'history': [
            {**self.bundle['history'][0], 'receipts': []}]}
        bad = Fernet(self.primary).encrypt(json.dumps(forged).encode())
        with self.assertRaises(ValueError):
            self.export(encrypted_checkpoint=bad,
                        source_blob_sha=git_blob_sha(bad))

    def test_restoration_never_returns_primary_or_recovery_secret(self):
        sealed = self.export()['private_encrypted_archive']
        check = inspect_offline_recovery_archive(
            sealed, recovery_key=self.recovery,
            trusted_public_keys=self.public)
        self.assertFalse(check['summary']['remote_github_state_verified'])
        new_key = Fernet.generate_key()
        out = prepare_offline_recovery_ciphertext(
            sealed, recovery_key=self.recovery,
            new_primary_key=new_key, trusted_public_keys=self.public,
            approve_offline_recovery=True)
        for data in (json.dumps(out['summary']), repr(check['summary'])):
            for secret in (WHO, FOLDER, SHEET):
                self.assertNotIn(secret, data)
        self.assertNotIn(self.primary, out['private_reencrypted_checkpoint'])
        self.assertNotIn(self.recovery, out['private_reencrypted_checkpoint'])


if __name__ == '__main__':
    unittest.main()
