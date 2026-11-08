"""Synthetic GitHub USD compute-credit checks; no Billing API access."""
import unittest
from supplier_docs.actions_budget_guard import assess_private_actions_allowance


class PrivateActionsBudgetTests(unittest.TestCase):
    def guard(self, **kw):
        data = {
            'billing_period': '2026-11',
            'usage_checked_period': None,
            'included_compute_usd': None,
            'consumed_compute_usd': None,
            'runner_rate_usd_per_minute': None,
            'planned_runs': 30,
            'max_minutes_per_run': 5,
            'reserve_usd': '1.00',
            'private_repo': True,
            'owner_verified_remaining': False,
            'hard_stop_budget_reviewed': False,
            'secret_controls_reviewed': False,
            'storage_billing_reviewed': False,
        }
        data.update(kw)
        return assess_private_actions_allowance(**data)

    def verified(self, **kw):
        return self.guard(
            usage_checked_period='2026-11',
            included_compute_usd='12.00',
            consumed_compute_usd='6.00',
            runner_rate_usd_per_minute='0.006',
            owner_verified_remaining=True, **kw)

    def test_unknown_account_usage_blocks_and_does_not_spend(self):
        r = self.guard()
        self.assertEqual(r['status'],
                         'blocked_until_current_billing_credit_verified')
        self.assertEqual(r['estimated_max_monthly_runner_minutes'], 150)
        self.assertIsNone(r['estimated_compute_usd'])
        self.assertFalse(r['workflow_activated'])
        self.assertFalse(r['additional_cost_guaranteed_zero'])

    def test_usd_pricing_example_uses_shared_credit_not_minutes(self):
        r = self.verified()
        self.assertEqual(r['estimated_compute_usd'], '0.900')
        self.assertEqual(r['post_plan_remaining_compute_credit_usd'], '5.100')
        self.assertEqual(r['status'],
                         'blocked_until_spending_stop_reviewed')

    def test_remaining_credit_reserve_blocks(self):
        r = self.guard(
            usage_checked_period='2026-11',
            included_compute_usd='12.00',
            consumed_compute_usd='11.50',
            runner_rate_usd_per_minute='0.006',
            owner_verified_remaining=True)
        self.assertEqual(r['status'],
                         'blocked_to_preserve_compute_credit_reserve')
        self.assertEqual(r['post_plan_remaining_compute_credit_usd'], '-0.400')

    def test_secret_and_storage_require_independent_reviews(self):
        r = self.verified(hard_stop_budget_reviewed=True)
        self.assertEqual(r['status'],
                         'blocked_until_private_secret_controls_reviewed')
        r = self.verified(hard_stop_budget_reviewed=True,
                          secret_controls_reviewed=True)
        self.assertEqual(r['status'],
                         'blocked_until_storage_billing_reviewed')
        self.assertFalse(
            r['private_environment_secrets_assumed_available_on_free_plan'])

    def test_complete_flags_only_reach_separate_security_review(self):
        r = self.verified(hard_stop_budget_reviewed=True,
                          secret_controls_reviewed=True,
                          storage_billing_reviewed=True)
        self.assertEqual(r['status'],
                         'eligible_for_separate_manual_security_review')
        self.assertFalse(r['workflow_activated'])
        self.assertFalse(r['billing_figures_verified_by_code'])

    def test_stale_billing_period_fails_closed(self):
        r = self.guard(
            usage_checked_period='2026-10', included_compute_usd='12.00',
            consumed_compute_usd='0', runner_rate_usd_per_minute='0.006',
            owner_verified_remaining=True)
        self.assertEqual(r['status'],
                         'blocked_until_current_billing_credit_verified')

    def test_partial_budget_data_rejected(self):
        with self.assertRaises(ValueError):
            self.guard(included_compute_usd='12.00')

    def test_invalid_budget_fields_rejected(self):
        invalid = [
            {'billing_period': '2026-99'},
            {'included_compute_usd': True},
            {'reserve_usd': '0'},
            {'reserve_usd': '-1'},
            {'planned_runs': 32},
            {'max_minutes_per_run': 100},
            {'owner_verified_remaining': 1},
            {'private_repo': False},
            {'storage_billing_reviewed': 'yes'},
        ]
        for kw in invalid:
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.guard(**kw)

    def test_no_fixed_2000_minutes_assumption_in_output(self):
        result = self.verified()
        self.assertNotIn('2000', str(result))
        self.assertIn('credit', result['status'] + str(result.keys()))


if __name__ == '__main__':
    unittest.main()
