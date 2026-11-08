"""Synthetic policy tests: no GitHub OIDC tokens, Google secrets or Cloud calls."""
import json
import unittest

from supplier_docs.github_wif_review import plan_private_github_wif


def valid():
    return {
        'private_repo': True,
        'repository': 'fake-owner/supplier-private-runner',
        'repository_id': '12345678901',
        'owner_id': '876543210',
        'branch_ref': 'refs/heads/main',
        'workflow_ref': ('fake-owner/supplier-private-runner/'
                         '.github/workflows/supplier-readonly.yml@refs/heads/main'),
        'event_name': 'workflow_dispatch',
        'reader_service_account': (
            'supplier-docs-reader@fake-supplier-project.iam.gserviceaccount.com'),
        'provider_resource': ('projects/123456789012/locations/global/'
                              'workloadIdentityPools/supplier-only-pool/'
                              'providers/supplier-github-oidc'),
        'provider_review_completed': False,
        'reader_share_scope_reviewed': False,
        'quota_and_billing_reviewed': False,
        'private_state_store_reviewed': False,
        'secret_json_keys_present': False,
        'live_access_enabled': False,
        'scheduled': False,
        'public_artifacts_enabled': False,
        'production_spapi_identity_reused': False,
    }


class PrivateGithubWIFTests(unittest.TestCase):
    def test_safe_unconfigured_proposal_is_not_labeled_active(self):
        cfg = valid()
        result = plan_private_github_wif(cfg)
        info = result['summary']
        self.assertEqual(info['status'], 'blocked_on_external_configuration_review')
        self.assertFalse(info['cloud_side_provider_condition_verified_by_this_check'])
        self.assertFalse(info['additional_cost_guaranteed_zero'])
        self.assertFalse(info['real_workflow_triggered'])
        self.assertEqual(info['cloud_iam_changes'], 0)
        self.assertNotIn('fake-owner', json.dumps(info))
        self.assertNotIn('12345678901', json.dumps(info))
        condition = result['private_required_provider_condition']
        self.assertIn("assertion.repository_owner_id=='876543210'", condition)
        self.assertIn("assertion.repository_id=='12345678901'", condition)
        self.assertIn("assertion.event_name=='workflow_dispatch'", condition)
        self.assertIn('assertion.workflow_ref', condition)

    def test_all_four_checks_are_needed_for_separate_review_not_execution(self):
        cfg = valid()
        for key in ('provider_review_completed', 'reader_share_scope_reviewed',
                    'quota_and_billing_reviewed', 'private_state_store_reviewed'):
            cfg[key] = True
        info = plan_private_github_wif(cfg)['summary']
        self.assertEqual(info['status'], 'eligible_for_separate_manual_test_review')
        self.assertFalse(info['real_workflow_triggered'])
        self.assertFalse(info['private_persistent_state_verified_by_this_check'])

    def test_public_repo_unsafe_live_and_scheduler_are_always_rejected(self):
        invalid = [
            ('private_repo', False),
            ('secret_json_keys_present', True),
            ('live_access_enabled', True),
            ('scheduled', True),
            ('public_artifacts_enabled', True),
            ('production_spapi_identity_reused', True),
        ]
        for key, val in invalid:
            config = valid()
            config[key] = val
            with self.subTest(key=key), self.assertRaises(ValueError):
                plan_private_github_wif(config)

    def test_workflow_and_pr_event_cannot_request_production_identity(self):
        invalid = [
            ('branch_ref', 'refs/heads/feature/x'),
            ('workflow_ref', 'fake-owner/supplier-private-runner/'
                             '.github/workflows/other.yml@refs/heads/main'),
            ('event_name', 'pull_request'),
            ('event_name', 'schedule'),
            ('reader_service_account',
             'amazon-spapi-worker@fake-supplier-project.iam.gserviceaccount.com'),
            ('provider_resource',
             'projects/123456789012/locations/global/'
             'workloadIdentityPools/spapi-pool/providers/oidc'),
        ]
        for key, val in invalid:
            config = valid()
            config[key] = val
            with self.subTest(key=key), self.assertRaises(ValueError):
                plan_private_github_wif(config)

    def test_invalid_or_mutable_repo_and_owner_identity_are_rejected(self):
        invalid = [
            ('repository_id', ''),
            ('repository_id', 'repo-name'),
            ('owner_id', 'fake-owner'),
            ('repository', 'bad owner/repo'),
            ('repository', 'owner/..'),
        ]
        for key, val in invalid:
            config = valid()
            config[key] = val
            with self.subTest(key=key), self.assertRaises(ValueError):
                plan_private_github_wif(config)

    def test_malformed_manifest_and_boolean_risks_refused(self):
        config = valid()
        config['unexpected_token'] = 'fake'
        with self.assertRaises(ValueError):
            plan_private_github_wif(config)
        config = valid()
        config['private_repo'] = 1
        with self.assertRaises(ValueError):
            plan_private_github_wif(config)

    def test_global_project_iam_is_never_granted(self):
        cfg = valid()
        result = plan_private_github_wif(cfg)
        self.assertNotIn('roles/owner', str(result))
        self.assertNotIn('roles/editor', str(result))
        self.assertNotIn('service_account_key', str(result))
        self.assertFalse(result['summary']['new_paid_service_provisioned'])


if __name__ == '__main__':
    unittest.main()
