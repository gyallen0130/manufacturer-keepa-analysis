"""Offline reference usage numbers; no billing account and no currency quote."""
import unittest
from supplier_docs.budget_review import estimate_pilot_usage


class BudgetPreflightTests(unittest.TestCase):

    def test_thirty_runs_of_two_minutes_are_bounded_and_not_free_guarantee(self):
        result = estimate_pilot_usage()
        self.assertEqual(result['cpu_seconds'], 3600)
        self.assertEqual(result['memory_gib_seconds'], 1800.0)
        self.assertTrue(result['within_reference_compute_allowances'])
        self.assertFalse(result['actual_billing_account_free_usage_known'])
        self.assertFalse(result['tokyo_region_cost_confirmed'])
        self.assertTrue(result['requires_billing_review_before_deployment'])
        self.assertFalse(result['automatic_execution_enabled'])

    def test_no_jobs_gives_zero_compute_not_zero_invoice(self):
        result = estimate_pilot_usage(runs_per_month=0)
        self.assertEqual(result['cpu_seconds'], 0)
        self.assertEqual(result['memory_gib_seconds'], 0)
        self.assertFalse(result['storage_registry_logs_network_cost_included'])

    def test_scheduler_secret_quotas_and_cpu_bounds_are_fail_closed(self):
        invalid = [
            {'runs_per_month': 32}, {'runs_per_month': -1},
            {'runs_per_month': True}, {'seconds_per_run': 601},
            {'seconds_per_run': 0}, {'vcpus': 2},
            {'memory_gib': 8.0}, {'active_secret_versions': 7},
            {'scheduler_jobs': 1}, {'scheduler_jobs': False},
        ]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                estimate_pilot_usage(**kwargs)

    def test_running_one_gib_uses_twice_the_memory(self):
        report = estimate_pilot_usage(runs_per_month=5,
                                      seconds_per_run=100, memory_gib=1.0)
        self.assertEqual(report['cpu_seconds'], 500)
        self.assertEqual(report['memory_gib_seconds'], 500.0)


if __name__ == '__main__':
    unittest.main()
