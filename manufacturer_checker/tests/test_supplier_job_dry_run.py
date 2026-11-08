"""Offline-only Cloud Run style process tests; all scenarios are fictional."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

from supplier_docs.job_dry_run import SCENARIOS, simulate


class SyntheticJobDryRunTests(unittest.TestCase):
    def test_each_crash_stage_has_expected_inert_action(self):
        expected = {
            'after_scan': 'resume_only_unreviewed_items',
            'partial_review': 'resume_only_unreviewed_items',
            'all_reviewed': 'ready_for_external_revalidation_not_committed',
            'cas_committed': 'halt_advanced_inventory_requires_journal_reconciliation',
            'cas_conflict': 'halt_concurrent_inventory_generation',
            'unchanged': 'no_changes_no_commit',
        }
        self.assertEqual(set(SCENARIOS), set(expected))
        for scenario, action in expected.items():
            with self.subTest(scenario=scenario):
                result = simulate(scenario)
                self.assertEqual(result['mode'], 'synthetic_offline_dry_run')
                self.assertEqual(result['action'], action)
                self.assertEqual(result['summary']['cloud_api_calls'], 0)
                self.assertFalse(result['summary']['baseline_advanced_by_this_check'])
                self.assertNotIn('supplier-docs/inventory.enc', json.dumps(result))
                self.assertNotIn('fake_sheet_', json.dumps(result))
                self.assertNotIn('fake_folder_', json.dumps(result))

    def test_job_cli_prints_only_synthetic_summary(self):
        root = Path(__file__).resolve().parents[1]
        command = [sys.executable, '-m', 'supplier_docs.job_dry_run',
                   '--scenario', 'partial_review']
        run = subprocess.run(command, cwd=root, text=True,
                             capture_output=True, timeout=20, check=True)
        self.assertEqual(run.stderr, '')
        report = json.loads(run.stdout)
        self.assertEqual(report['scenario'], 'partial_review')
        self.assertEqual(report['summary']['reviewed'], 1)
        self.assertEqual(report['summary']['retry_pending'], 1)
        self.assertNotIn('fake_', run.stdout)

    def test_live_mode_and_unsafe_flags_are_not_supported(self):
        root = Path(__file__).resolve().parents[1]
        for args in [['--live'], ['--scenario', 'production'],
                     ['--schedule-enabled'], ['--approve-all']]:
            with self.subTest(args=args):
                run = subprocess.run(
                    [sys.executable, '-m', 'supplier_docs.job_dry_run', *args],
                    cwd=root, text=True, capture_output=True, timeout=20)
                self.assertNotEqual(run.returncode, 0)
                self.assertEqual(run.stdout, '')

    def test_unknown_scenario_fails_closed_before_simulation(self):
        with self.assertRaises(ValueError):
            simulate('production')


if __name__ == '__main__':
    unittest.main()
