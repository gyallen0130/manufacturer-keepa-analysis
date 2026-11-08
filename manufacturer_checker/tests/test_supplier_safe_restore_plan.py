"""Synthetic-only manual recovery gate: no GitHub API, keys or live Drive."""
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
)
from supplier_docs.offline_recovery_archive import (
    create_offline_recovery_archive,
)
from supplier_docs.safe_restore_plan import (
    assess_manual_restore, prepare_manually_checked_recovery,
)

FOLDER = 'fake_folder_recoveryabc123'
FILE = 'fake_sheet_recoverydef456'
REVIEWER = 'fake_reviewer_recovery01'
MIME = 'application/vnd.google-apps.spreadsheet'


def inventory(version):
    return {FOLDER: {
        'schema_version': SCHEMA_VERSION, 'folder_id': FOLDER,
        'files': {FILE: {
            'mime_type': MIME, 'version': version,
            'modified_time': ''}},
        'total_items': 1, 'pages_scanned': 1,
        'unsupported_items': 0, 'unscanned_subfolders': 0,
    }}


def sha(cipher):
    return hashlib.sha1(
        b'blob ' + str(len(cipher)).encode() + b'\0' + cipher).hexdigest()


def checks():
    return {
        'private_repository_ownership_confirmed': True,
        'separate_backup_location_confirmed': True,
        'recovery_key_stored_separately': True,
        'trusted_reviewer_registry_confirmed': True,
        'drive_source_revisions_checked': True,
        'owner_approved_manual_recovery': True,
    }


class ManualRestoreGateTests(unittest.TestCase):
    def setUp(self):
        self.primary = Fernet.generate_key()
        self.recovery = Fernet.generate_key()
        signer = Ed25519PrivateKey.generate()
        self.public = {REVIEWER: signer.public_key()}
        old, new = inventory('1'), inventory('2')
        signed = issue_offline_ed25519_receipt(
            old, new, folder_id=FOLDER, file_id=FILE, event='changed',
            reviewer_id=REVIEWER, evidence_ref='fake_review_evidence123',
            private_key=signer,
            reviewed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        initial = initialize_audit_bundle(
            old, approve_initial_baseline=True)
        self.bundle = propose_next_audit_bundle(
            initial, new, receipts=[signed],
            trusted_public_keys=self.public)
        self.remote = Fernet(self.primary).encrypt(
            json.dumps(self.bundle).encode())
        self.remote_sha = sha(self.remote)
        self.backup = create_offline_recovery_archive(
            self.remote, primary_key=self.primary,
            recovery_key=self.recovery,
            source_blob_sha=self.remote_sha,
            trusted_public_keys=self.public)['private_encrypted_archive']

    def assess(self, **overrides):
        args = dict(
            archive=self.backup,
            recovery_key=self.recovery,
            trusted_public_keys=self.public,
            observed_remote_ciphertext=self.remote,
            observed_remote_blob_sha=self.remote_sha,
            **checks(),
        )
        args.update(overrides)
        return assess_manual_restore(**args)

    def test_same_remote_and_complete_checks_only_permit_preparation(self):
        result = self.assess()
        self.assertEqual(result['action'],
                         'local_reencryption_preparation_only')
        info = result['summary']
        self.assertTrue(info['remote_matches_backup_source'])
        self.assertTrue(info['backup_signatures_reverified'])
        self.assertFalse(info['restoration_committed'])
        self.assertFalse(info['operator_assertions_independently_verified'])
        self.assertEqual(info['github_or_drive_calls'], 0)
        self.assertNotIn(FOLDER, json.dumps(info))
        self.assertNotIn(FILE, json.dumps(info))

    def test_remote_unavailable_halts_even_with_owner_approval(self):
        p = self.assess(
            observed_remote_ciphertext=None,
            observed_remote_blob_sha=None)
        self.assertEqual(p['action'], 'halt_remote_state_unavailable')
        self.assertFalse(p['summary']['remote_matches_backup_source'])

    def test_newer_remote_rejects_old_backup_without_auto_rollback(self):
        newer = Fernet(self.primary).encrypt(b'newer private checkpoint')
        p = self.assess(
            observed_remote_ciphertext=newer,
            observed_remote_blob_sha=sha(newer))
        self.assertEqual(p['action'], 'halt_backup_stale_or_remote_changed')
        self.assertFalse(p['summary']['restoration_committed'])

    def test_false_or_missing_manual_checks_block_recovery(self):
        for name in checks():
            p = self.assess(**{name: False})
            with self.subTest(name=name):
                self.assertEqual(
                    p['action'], 'halt_manual_custody_and_source_checks_incomplete')

    def test_invalid_metadata_and_malformed_manual_flags_rejected(self):
        for kwargs in [
            {'observed_remote_blob_sha': '0' * 40},
            {'observed_remote_blob_sha': 'notsha'},
            {'observed_remote_ciphertext': b'bad'},
            {'owner_approved_manual_recovery': 'yes'},
            {'private_repository_ownership_confirmed': 1},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.assess(**kwargs)

    def test_correct_keys_required_and_signature_history_replayed(self):
        with self.assertRaises(ValueError):
            self.assess(recovery_key=Fernet.generate_key())
        with self.assertRaises(ValueError):
            self.assess(trusted_public_keys={
                REVIEWER: Ed25519PrivateKey.generate().public_key()})

    def test_prepare_reencrypts_locally_only_with_remote_match(self):
        new_key = Fernet.generate_key()
        prepared = prepare_manually_checked_recovery(
            self.backup, recovery_key=self.recovery,
            new_primary_key=new_key,
            trusted_public_keys=self.public,
            observed_remote_ciphertext=self.remote,
            observed_remote_blob_sha=self.remote_sha,
            **checks())
        self.assertEqual(
            json.loads(Fernet(new_key).decrypt(
                prepared['private_reencrypted_checkpoint'])),
            self.bundle)
        self.assertTrue(prepared['summary']['new_ciphertext_prepared'])
        self.assertFalse(prepared['summary']['remote_write_performed'])
        self.assertNotIn(self.recovery,
                         prepared['private_reencrypted_checkpoint'])

    def test_prepare_rejects_stale_remote_and_missing_source_review(self):
        newer = Fernet(self.primary).encrypt(b'other encrypted state')
        with self.assertRaises(ValueError):
            prepare_manually_checked_recovery(
                self.backup, recovery_key=self.recovery,
                new_primary_key=Fernet.generate_key(),
                trusted_public_keys=self.public,
                observed_remote_ciphertext=newer,
                observed_remote_blob_sha=sha(newer),
                **checks())
        incomplete = checks()
        incomplete['drive_source_revisions_checked'] = False
        with self.assertRaises(ValueError):
            prepare_manually_checked_recovery(
                self.backup, recovery_key=self.recovery,
                new_primary_key=Fernet.generate_key(),
                trusted_public_keys=self.public,
                observed_remote_ciphertext=self.remote,
                observed_remote_blob_sha=self.remote_sha,
                **incomplete)


if __name__ == '__main__':
    unittest.main()
