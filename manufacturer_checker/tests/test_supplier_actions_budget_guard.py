"""Synthetic GitHub minutes and budget decision tests; no external billing data."""
import json
import unittest

from supplier_docs.actions_budget_guard import assess_private_actions_allowance


class PrivateActionsBudgetTests(unittest.TestCase):
    def run_guard(self, **override):
        inputs = {
            'billing_period': '2026-11',
            'usage_checked_period': None,
            'account_included_minutes': None,
            'already_used_minutes': None,
            'planned_runs': 30,
            'max_minutes_per_run': 5,
            'reserve_minutes': 120,
            'private_repo': True,
            'owner_verified_remaining': False,
            'hard_stop_budget_reviewed': False,
            'secret_controls_reviewed': False,
        }
        inputs.update(override)
        return assess_private_actions_allowance(**inputs)

    def verified(self, **override):
        return self.run_guard(
            usage_checked_period='2026-11',
            account_included_minutes=2000,
            already_used_minutes=1000,
            owner_verified_remaining=True,
            **override)

    def test_unknown_account_usage_is_a_hard_block(self):
        output = self.run_guard()
        self.assertEqual(output['status'],
                         'blocked_until_billing_usage_verified')
        self.assertIsNone(output['post_plan_remaining_minutes_estimate'])
        self.assertEqual(output['planned_max_monthly_minutes'], 150)
        self.assertFalse(output['workflow_activated'])
        self.assertFalse(output['budget_changed'])
        self.assertFalse(output['additional_cost_guaranteed_zero'])

    def test_verified_usage_without_stopping_budget_still_blocks(self):
        output = self.verified()
        self.assertEqual(output['post_plan_remaining_minutes_estimate'], 850)
        self.assertEqual(output['status'],
                         'blocked_until_hard_spending_stop_reviewed')

    def test_private_secret_review_is_separate_gate(self):
        output = self.verified(hard_stop_budget_reviewed=True)
        self.assertEqual(output['status'],
                         'blocked_until_private_secret_controls_reviewed')
        self.assertFalse(
            output['private_environment_secrets_assumed_available_on_free_plan'])
        self.assertTrue(output['private_repo_secret_access_requires_workflow_review'])

    def test_full_check_is_only_eligible_for_manual_review_not_deployed(self):
        output = self.verified(
            hard_stop_budget_reviewed=True,
            secret_controls_reviewed=True)
        self.assertEqual(output['status'],
                         'eligible_for_separate_manual_security_review')
        self.assertFalse(output['additional_cost_guaranteed_zero'])
        self.assertFalse(output['workflow_activated'])

    def test_reserve_is_not_consumed_by_estimated_workload(self):
        output = self.verified(already_used_minutes=1000) if False else None
        output = self.run_guard(
            usage_checked_period='2026-11', account_included_minutes=2000,
            already_used_minutes=1800, owner_verified_remaining=True,
            hard_stop_budget_reviewed=True,
            secret_controls_reviewed=True)
        self.assertEqual(output['status'],
                         'blocked_to_preserve_free_minute_reserve')
        self.assertEqual(output['post_plan_remaining_minutes_estimate'], 50)

    def test_stale_owner_billing_check_is_not_usable(self):
        output = self.run_guard(
            usage_checked_period='2026-10', account_included_minutes=2000,
            already_used_minutes=0, owner_verified_remaining=True)
        self.assertEqual(output['status'],
                         'blocked_until_billing_usage_verified')
        self.assertIsNone(output['post_plan_remaining_minutes_estimate'])

    def test_invalid_usage_or_scope_is_rejected(self):
        invalid = [
            {'billing_period': '2026-13'},
            {'usage_checked_period': '2026-99'},
            {'account_included_minutes': -1},
            {'already_used_minutes': True},
            {'planned_runs': 50},
            {'max_minutes_per_run': 60},
            {'reserve_minutes': 0},
            {'private_repo': False},
            {'owner_verified_remaining': 1},
        ]
        for kw in invalid:
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.run_guard(**kw)

    def test_summary_has_no_secret_identifiers_or_real_account_data(self):
        output = self.verified()
        encoded = json.dumps(output)
        self.assertNotIn('fake-owner', encoded)
        self.assertNotIn('supplier-docs-reader@', encoded)
        self.assertNotIn('secret_token', encoded)


if __name__ == '__main__':
    unittest.main()
