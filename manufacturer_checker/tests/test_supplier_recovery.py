"""Synthetic crash / replay tests; no Cloud Run, Drive or GCS calls."""
from datetime import datetime, timezone
import json
import unittest

from supplier_docs.drive_delta import SCHEMA_VERSION
from supplier_docs.recovery import assess_recovery
from supplier_docs.review_gate import issue_review_receipt

FOLDER = 'fake_folder_testabc123'
FILE_A = 'fake_sheet_testabc123'
FILE_B = 'fake_sheet_testdef456'
FILE_GONE = 'fake_sheet_testghi789'
MIME = 'application/vnd.google-apps.spreadsheet'
SIGNING_KEY = b'only-for-synthetic-fault-injection-1234'
ACTORS = {'fake_reviewer_1'}
STAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)


def inventory(data):
    return {FOLDER: {
        'schema_version': SCHEMA_VERSION, 'folder_id': FOLDER,
        'files': {key: {
            'mime_type': MIME, 'version': version, 'modified_time': ''}
            for key, version in data.items()},
        'total_items': len(data), 'pages_scanned': 1,
        'unsupported_items': 0, 'unscanned_subfolders': 0,
    }}


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.before = inventory({FILE_A: '1', FILE_GONE: '1'})
        self.proposed = inventory({FILE_A: '2', FILE_B: '1'})

    def receipt(self, document, event='changed'):
        return issue_review_receipt(
            self.before, self.proposed,
            folder_id=FOLDER, file_id=document, event=event,
            reviewer_id='fake_reviewer_1', evidence_ref='fake_evidence_1234',
            signing_key=SIGNING_KEY, reviewed_at=STAMP)

    def assess(self, *, receipts=(), persisted=None,
               expected_generation=3, observed_generation=3,
               proposed=None, before=None):
        return assess_recovery(
            self.before if before is None else before,
            self.proposed if proposed is None else proposed,
            self.before if persisted is None else persisted,
            receipts=receipts, signing_key=SIGNING_KEY,
            allowed_reviewers=ACTORS, expected_generation=expected_generation,
            observed_generation=observed_generation)

    def test_crash_after_scan_retries_all_pending_documents(self):
        p = self.assess()
        self.assertEqual(p['action'], 'resume_only_unreviewed_items')
        self.assertEqual(p['summary']['retry_pending'], 2)
        self.assertEqual(p['summary']['access_review_pending'], 1)
        self.assertFalse(p['summary']['baseline_advanced_by_this_check'])

    def test_crash_after_one_receipt_skips_only_verified_document(self):
        p = self.assess(receipts=[self.receipt(FILE_A)])
        self.assertEqual(p['action'], 'resume_only_unreviewed_items')
        self.assertEqual(p['summary']['reviewed'], 1)
        self.assertEqual(p['summary']['retry_pending'], 1)
        self.assertEqual(p['summary']['access_review_pending'], 1)

    def test_everything_reviewed_still_requires_external_revalidation(self):
        receipts = [self.receipt(FILE_A), self.receipt(FILE_B),
                    self.receipt(FILE_GONE, 'unavailable')]
        p = self.assess(receipts=receipts)
        self.assertEqual(p['action'],
                         'ready_for_external_revalidation_not_committed')
        self.assertEqual(p['summary']['retry_pending'], 0)
        self.assertFalse(p['summary']['baseline_advanced_by_this_check'])
        self.assertEqual(p['summary']['cloud_api_calls'], 0)

    def test_crash_after_cas_halts_until_journal_reconciled(self):
        receipts = [self.receipt(FILE_A), self.receipt(FILE_B),
                    self.receipt(FILE_GONE, 'unavailable')]
        p = self.assess(receipts=receipts, persisted=self.proposed,
                        expected_generation=3, observed_generation=4)
        self.assertEqual(
            p['action'], 'halt_advanced_inventory_requires_journal_reconciliation')
        self.assertFalse(p['summary']['baseline_advanced_by_this_check'])

    def test_stale_generation_detects_competing_writer_even_if_data_matches(self):
        p = self.assess(observed_generation=4)
        self.assertEqual(p['action'], 'halt_concurrent_inventory_generation')

    def test_unexpected_inventory_halts_and_does_not_overwrite(self):
        alien = inventory({FILE_A: '9', FILE_B: '2'})
        p = self.assess(persisted=alien)
        self.assertEqual(p['action'], 'halt_unexpected_persisted_inventory')

    def test_unchanged_scan_does_not_write_and_is_not_approved(self):
        p = self.assess(proposed=self.before)
        self.assertEqual(p['action'], 'no_changes_no_commit')
        self.assertEqual(p['summary']['review_items'], 0)

    def test_stale_or_forged_receipts_abort_recovery(self):
        good = self.receipt(FILE_A)
        bad = {**good, 'reviewer_id': 'other_actor'}
        for receipts in ([bad], [good, good]):
            with self.subTest(receipts=receipts), self.assertRaises(ValueError):
                self.assess(receipts=receipts)
        changed_again = inventory({FILE_A: '3', FILE_B: '1'})
        with self.assertRaises(ValueError):
            self.assess(receipts=[good], proposed=changed_again)

    def test_invalid_generation_rejected(self):
        for value in (0, -1, '3', True, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.assess(expected_generation=value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.assess(observed_generation=value)

    def test_summary_never_contains_supplier_ids_or_secrets(self):
        p = self.assess(receipts=[self.receipt(FILE_A)])
        report = json.dumps(p, ensure_ascii=False)
        for secret in (FOLDER, FILE_A, FILE_B, FILE_GONE,
                       'fake_reviewer_1', 'fake_evidence_1234'):
            self.assertNotIn(secret, report)


if __name__ == '__main__':
    unittest.main()
