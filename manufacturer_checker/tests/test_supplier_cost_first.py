"""Synthetic-only cost-first architecture and public-key review tests."""
from datetime import datetime, timezone
import json
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from supplier_docs.cost_first import evaluate_cost_first_plan
from supplier_docs.drive_delta import SCHEMA_VERSION
from supplier_docs.offline_review import (
    issue_offline_ed25519_receipt,
    plan_offline_ed25519_retries,
    finalize_with_offline_ed25519_receipts,
)

FOLDER = 'fake_folder_abcdef123'
A = 'fake_sheet_abcdef123'
B = 'fake_sheet_qwerty987'
UNCHANGED = 'fake_sheet_untouched123'
MIME = 'application/vnd.google-apps.spreadsheet'
STAMP = datetime(2026, 1, 1, 9, 20, tzinfo=timezone.utc)
REVIEWER = 'fake_reviewer_01'


def state(versions):
    return {FOLDER: {
        'schema_version': SCHEMA_VERSION, 'folder_id': FOLDER,
        'files': {fid: {
            'mime_type': MIME, 'version': version,
            'modified_time': ''} for fid, version in versions.items()},
        'total_items': len(versions), 'pages_scanned': 1,
        'unsupported_items': 0, 'unscanned_subfolders': 0,
    }}


def cost_plan():
    return {
        'runner': 'existing_github_actions',
        'new_paid_service': False,
        'recurring_charge_estimate_jpy': 0,
        'secret_business_data_in_public_repo': False,
        'confidential_logs_or_artifacts': False,
        'persistent_state_ready': False,
        'execution_enabled': False,
        'owner_approved_extra_cost': False,
        'shared_free_quota_verified': False,
    }


class CostFirstPolicyTests(unittest.TestCase):

    def test_existing_actions_is_candidate_but_not_deployed_or_free_guaranteed(self):
        p = evaluate_cost_first_plan(cost_plan())
        self.assertEqual(p['status'], 'design_only_state_storage_unresolved')
        self.assertFalse(p['zero_extra_cost_guaranteed'])
        self.assertFalse(p['additional_security_review_required'] is False)
        self.assertEqual(p['cloud_resources_created'], 0)
        self.assertEqual(p['automations_activated'], 0)

    def test_new_gcp_resources_require_explicit_cost_review(self):
        c = cost_plan()
        c['runner'] = 'new_gcp_resources'
        with self.assertRaises(ValueError):
            evaluate_cost_first_plan(c)
        c['new_paid_service'] = True
        self.assertEqual(evaluate_cost_first_plan(c)['status'],
                         'blocked_pending_explicit_cost_approval')
        c['owner_approved_extra_cost'] = True
        self.assertEqual(evaluate_cost_first_plan(c)['status'],
                         'design_only_state_storage_unresolved')

    def test_unknown_cost_blocks_until_explicit_approval(self):
        c = cost_plan()
        c['recurring_charge_estimate_jpy'] = None
        self.assertEqual(evaluate_cost_first_plan(c)['status'],
                         'blocked_pending_explicit_cost_approval')

    def test_secret_data_in_public_or_logs_never_allowed(self):
        for flag in ('secret_business_data_in_public_repo',
                     'confidential_logs_or_artifacts', 'execution_enabled'):
            c = cost_plan()
            c[flag] = True
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                evaluate_cost_first_plan(c)

    def test_only_after_storage_and_quota_checks_does_security_review_begin(self):
        c = cost_plan()
        c['persistent_state_ready'] = True
        self.assertEqual(evaluate_cost_first_plan(c)['status'],
                         'design_only_free_quota_unverified')
        c['shared_free_quota_verified'] = True
        self.assertEqual(evaluate_cost_first_plan(c)['status'],
                         'eligible_for_separate_security_and_access_review')
        self.assertFalse(evaluate_cost_first_plan(c)['zero_extra_cost_guaranteed'])

    def test_malformed_cost_and_runner_are_rejected(self):
        for field, value in [('recurring_charge_estimate_jpy', -1),
                             ('recurring_charge_estimate_jpy', True),
                             ('runner', 'unsafe'),
                             ('owner_approved_extra_cost', 1)]:
            c = cost_plan()
            c[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                evaluate_cost_first_plan(c)


class PublicKeyOfflineReviewTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.trusted = {REVIEWER: self.key.public_key()}
        self.old = state({A: '1', UNCHANGED: '1'})
        self.new = state({A: '2', B: '1', UNCHANGED: '1'})

    def receipt(self, file_id=A, *, current=None, reviewer=REVIEWER):
        return issue_offline_ed25519_receipt(
            self.old, self.new if current is None else current,
            folder_id=FOLDER, file_id=file_id, event='changed',
            reviewer_id=reviewer, evidence_ref='fake_evidence_123',
            private_key=self.key, reviewed_at=STAMP)

    def plan(self, receipts, *, current=None, trusted=None):
        return plan_offline_ed25519_retries(
            self.old, self.new if current is None else current,
            receipts=receipts,
            trusted_public_keys=self.trusted if trusted is None else trusted)

    def test_worker_only_needs_public_key_to_verify_review(self):
        receipt = self.receipt()
        summary = self.plan([receipt])['summary']
        self.assertEqual(summary['verified_receipts'], 1)
        self.assertEqual(summary['retry_pending'], 1)
        self.assertFalse(summary['review_worker_has_signing_capability'])
        self.assertFalse(summary['additional_signing_service_required'])
        self.assertFalse(summary['baseline_advanced'])
        self.assertNotIn(FOLDER, json.dumps(summary))

    def test_complete_reviews_can_finalize_but_no_disk_or_network_io(self):
        receipts = [self.receipt(A), self.receipt(B)]
        plan = self.plan(receipts)
        self.assertTrue(plan['summary']['ready_to_finalize'])
        self.assertEqual(finalize_with_offline_ed25519_receipts(
            self.old, self.new, receipts=receipts,
            trusted_public_keys=self.trusted), self.new)

    def test_missing_review_must_not_finalize(self):
        with self.assertRaises(ValueError):
            finalize_with_offline_ed25519_receipts(
                self.old, self.new, receipts=[self.receipt()],
                trusted_public_keys=self.trusted)

    def test_tampering_wrong_key_and_duplicates_rejected(self):
        original = self.receipt()
        for bad in [{**original, 'reviewer_id': 'somebody_else'},
                    {**original, 'evidence_ref': 'changed_evidence_123'},
                    {**original, 'signature': '0' * 128}]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.plan([bad])
        self.assertRaises(ValueError, self.plan, [original, original])
        other_public = Ed25519PrivateKey.generate().public_key()
        with self.assertRaises(ValueError):
            self.plan([original], trusted={REVIEWER: other_public})

    def test_revision_is_pinned_and_unchanged_file_cannot_be_signed(self):
        old_receipt = self.receipt()
        next_revision = state({A: '3', B: '1', UNCHANGED: '1'})
        with self.assertRaises(ValueError):
            self.plan([old_receipt], current=next_revision)
        with self.assertRaises(ValueError):
            self.receipt(UNCHANGED)

    def test_missing_key_invalid_timestamp_and_unknown_source_rejected(self):
        with self.assertRaises(ValueError):
            issue_offline_ed25519_receipt(
                self.old, self.new, folder_id=FOLDER, file_id=A,
                event='changed', reviewer_id=REVIEWER,
                evidence_ref='fake_evidence_123', private_key=b'invalid',
                reviewed_at=STAMP)
        with self.assertRaises(ValueError):
            issue_offline_ed25519_receipt(
                self.old, self.new, folder_id=FOLDER, file_id=A,
                event='changed', reviewer_id=REVIEWER,
                evidence_ref='fake_evidence_123', private_key=self.key,
                reviewed_at=datetime(2026, 1, 1))
        with self.assertRaises(ValueError):
            self.receipt('fake_unknown_123456')
        with self.assertRaises(ValueError):
            self.plan([self.receipt()], trusted={})

    def test_report_contains_no_supplier_identifiers(self):
        output = self.plan([self.receipt(A)])['summary']
        for private in (FOLDER, A, B, UNCHANGED, REVIEWER,
                        'fake_evidence_123'):
            self.assertNotIn(private, json.dumps(output))


if __name__ == '__main__':
    unittest.main()
