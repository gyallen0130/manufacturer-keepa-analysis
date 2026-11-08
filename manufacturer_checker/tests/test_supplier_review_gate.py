"""Offline review receipt tests with synthetic Drive IDs and throwaway HMAC key."""
from datetime import datetime, timezone
import json
import unittest

from supplier_docs.drive_delta import SCHEMA_VERSION
from supplier_docs.review_gate import (
    finalize_with_verified_receipts, issue_review_receipt, plan_review_retries,
)

FOLDER = 'fake_folder_abcdef123'
SHEET = 'fake_sheet_abcdef123'
UNAVAILABLE = 'fake_sheet_removed123'
BINARY = 'fake_excel_abcdef123'
UNTOUCHED = 'fake_sheet_untouched1'
MIME_SHEET = 'application/vnd.google-apps.spreadsheet'
MIME_EXCEL = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
KEY = b'development-only-fake-review-key-' * 2
ACTORS = {'reviewer_test_1'}
TIME = datetime(2026, 1, 1, 9, 30, tzinfo=timezone.utc)


def snapshot(files):
    return {FOLDER: {
        'schema_version': SCHEMA_VERSION, 'folder_id': FOLDER,
        'files': {
            fid: {'mime_type': mime, 'version': version, 'modified_time': ''}
            for fid, (mime, version) in files.items()},
        'total_items': len(files), 'unsupported_items': 0,
        'unscanned_subfolders': 0, 'pages_scanned': 1,
    }}


class ReviewGateTests(unittest.TestCase):
    def setUp(self):
        self.before = snapshot({
            SHEET: (MIME_SHEET, '1'),
            UNAVAILABLE: (MIME_SHEET, '2'),
            UNTOUCHED: (MIME_SHEET, '1')})
        self.current = snapshot({
            SHEET: (MIME_SHEET, '3'),
            BINARY: (MIME_EXCEL, '1'),
            UNTOUCHED: (MIME_SHEET, '1')})

    def receipt(self, file_id, event='changed', *, previous=None, current=None,
                key=KEY, evidence='ev_demo_12345678'):
        return issue_review_receipt(
            previous or self.before, current or self.current,
            folder_id=FOLDER, file_id=file_id, event=event,
            reviewer_id='reviewer_test_1', evidence_ref=evidence,
            signing_key=key, reviewed_at=TIME)

    def plan(self, receipts, *, previous=None, current=None, key=KEY,
             reviewers=None):
        return plan_review_retries(
            previous or self.before, current or self.current, receipts=receipts,
            signing_key=key,
            allowed_reviewers=ACTORS if reviewers is None else reviewers)

    def test_unreviewed_changes_retry_and_unavailable_stays_review_only(self):
        state = self.plan([])
        self.assertEqual(state['summary']['total_changes_needing_review'], 3)
        self.assertEqual(state['summary']['retry_pending'], 2)
        self.assertEqual(state['summary']['access_review_pending'], 1)
        self.assertFalse(state['summary']['ready_to_finalize'])
        self.assertIn((FOLDER, SHEET), state['private_retry_locations'])
        self.assertNotIn((FOLDER, UNTOUCHED), state['private_retry_locations'])
        for identifier in (FOLDER, SHEET, UNAVAILABLE, BINARY):
            self.assertNotIn(identifier, json.dumps(state['summary']))
        self.assertFalse(state['summary']['baseline_advanced'])
        with self.assertRaises(ValueError):
            finalize_with_verified_receipts(
                self.before, self.current, receipts=[], signing_key=KEY,
                allowed_reviewers=ACTORS)

    def test_partial_success_is_restartable_without_rereading_approved_files(self):
        one = self.receipt(SHEET)
        first = self.plan([one])
        self.assertEqual(first['summary']['verified_receipts'], 1)
        self.assertEqual(first['summary']['retry_pending'], 1)
        self.assertEqual(first['private_retry_locations'], [(FOLDER, BINARY)])
        restarted = self.plan([one])
        self.assertEqual(first, restarted)
        self.assertFalse(restarted['summary']['ready_to_finalize'])

    def test_finalization_requires_all_receipts_and_returns_only_data(self):
        receipts = [self.receipt(SHEET), self.receipt(BINARY),
                    self.receipt(UNAVAILABLE, 'unavailable')]
        plan = self.plan(receipts)
        self.assertEqual(plan['summary']['verified_receipts'], 3)
        self.assertTrue(plan['summary']['ready_to_finalize'])
        result = finalize_with_verified_receipts(
            self.before, self.current, receipts=receipts,
            signing_key=KEY, allowed_reviewers=ACTORS)
        self.assertEqual(result, self.current)
        self.assertEqual(self.before[FOLDER]['files'][SHEET]['version'], '1')

    def test_signed_receipt_is_bound_to_exact_revision(self):
        old = self.receipt(SHEET)
        changed_again = snapshot({
            SHEET: (MIME_SHEET, '4'),
            BINARY: (MIME_EXCEL, '1'),
            UNTOUCHED: (MIME_SHEET, '1')})
        with self.assertRaises(ValueError):
            self.plan([old], current=changed_again)

    def test_signed_receipt_requires_correct_key(self):
        with self.assertRaises(ValueError):
            self.plan([self.receipt(SHEET)], key=b'wrong-key-' * 4)
        with self.assertRaises(ValueError):
            self.receipt(SHEET, key=b'too-short')

    def test_tampering_identity_timestamp_or_evidence_rejected(self):
        good = self.receipt(SHEET)
        changes = [
            {'file_id': BINARY},
            {'reviewer_id': 'reviewer_test_2'},
            {'evidence_ref': 'ev_replaced_123456'},
            {'reviewed_at_utc': '2026-01-02T09:30:00Z'},
            {'signature': '0' * 64},
        ]
        for delta in changes:
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                self.plan([{**good, **delta}])

    def test_duplicate_or_unknown_receipts_rejected(self):
        good = self.receipt(SHEET)
        with self.assertRaises(ValueError):
            self.plan([good, good])
        with self.assertRaises(ValueError):
            self.receipt(UNTOUCHED)
        with self.assertRaises(ValueError):
            self.receipt('fake_sheet_notthere_12345')

    def test_unknown_actor_and_invalid_timestamp_rejected(self):
        good = self.receipt(SHEET)
        with self.assertRaises(ValueError):
            self.plan([good], reviewers={'other_reviewer'})
        with self.assertRaises(ValueError):
            self.plan([{**good, 'reviewed_at_utc': '2026-99-90T09:30:00Z'}])
        with self.assertRaises(ValueError):
            self.receipt(SHEET, evidence='bad')
        with self.assertRaises(ValueError):
            self.receipt(SHEET, evidence=' ' * 20)

    def test_unavailable_receipt_does_not_mean_deletion(self):
        only = self.receipt(UNAVAILABLE, 'unavailable')
        plan = self.plan([only])
        self.assertEqual(plan['summary']['access_review_pending'], 0)
        self.assertEqual(plan['summary']['retry_pending'], 2)
        self.assertIn((FOLDER, UNAVAILABLE, 'unavailable'),
                      plan['private_verified_locations'])
        self.assertNotIn('deleted', json.dumps(plan, ensure_ascii=False))

    def test_manifest_change_and_initial_baseline_rejected(self):
        with self.assertRaises(ValueError):
            plan_review_retries(
                None, self.current, receipts=[], signing_key=KEY,
                allowed_reviewers=ACTORS)
        with self.assertRaises(ValueError):
            self.plan([], reviewers=set())

    def test_no_receipts_are_issued_by_pure_retry_planner(self):
        original = self.receipt(SHEET)
        self.plan([original])
        self.assertNotIn('issued_receipts', self.plan([original]))
        self.assertFalse(self.plan([original])['summary']['baseline_advanced'])


if __name__ == '__main__':
    unittest.main()
