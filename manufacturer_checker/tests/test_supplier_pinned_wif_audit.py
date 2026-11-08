"""Offline-only fake GCP/GitHub configuration readback regression.

No live IAM read/write, GCP WIF token, GitHub repo secrets, or real supplier IDs.
"""
from copy import deepcopy
import json
import unittest

from supplier_docs.pinned_wif_audit import (
    expected_pinned_provider_condition, review_observed_reader_wif,
)

SHA = 'a' * 40
SOURCE_SHA = 'b' * 40
REPO = 'fake-owner/fake-private-supplier-reader'
ID = '12345678901'
OWNER_ID = '876543210'
PROJECT_NUMBER = '123456789012'
POOL = 'fake-supplier-pool'
PROVIDER = (
    f'projects/{PROJECT_NUMBER}/locations/global/'
    f'workloadIdentityPools/{POOL}/providers/fake-github-oidc'
)
SA = 'supplier-docs-reader@fake-supplier-project.iam.gserviceaccount.com'
REF = REPO + '/.github/workflows/supplier-readonly.yml@refs/heads/main'


def settings():
    return {
        'private_repo': True,
        'repository': REPO,
        'repository_id': ID,
        'owner_id': OWNER_ID,
        'branch_ref': 'refs/heads/main',
        'workflow_ref': REF,
        'event_name': 'workflow_dispatch',
        'reader_service_account': SA,
        'provider_resource': PROVIDER,
        'provider_review_completed': True,
        'reader_share_scope_reviewed': True,
        'quota_and_billing_reviewed': True,
        'private_state_store_reviewed': True,
        'secret_json_keys_present': False,
        'live_access_enabled': False,
        'scheduled': False,
        'public_artifacts_enabled': False,
        'production_spapi_identity_reused': False,
    }


def snapshots():
    cfg = settings()
    github = {
        'id': int(ID),
        'owner': {'id': int(OWNER_ID)},
        'full_name': REPO,
        'visibility': 'private',
        'default_branch': 'main',
        'default_branch_protected': False,
        'archived': False,
    }
    provider = {
        'name': PROVIDER, 'state': 'ACTIVE', 'disabled': False,
        'oidc': {
            'issuerUri': 'https://token.actions.githubusercontent.com',
            'allowedAudiences': [],
        },
        'attributeMapping': {
            'google.subject': 'assertion.sub',
            'attribute.repository_owner_id': 'assertion.repository_owner_id',
            'attribute.repository_id': 'assertion.repository_id',
            'attribute.ref': 'assertion.ref',
            'attribute.event_name': 'assertion.event_name',
            'attribute.workflow_ref': 'assertion.workflow_ref',
            'attribute.workflow_sha': 'assertion.workflow_sha',
            'attribute.sha': 'assertion.sha',
            'attribute.repository_visibility': 'assertion.repository_visibility',
            'attribute.runner_environment': 'assertion.runner_environment',
        },
        'attributeCondition': expected_pinned_provider_condition(cfg, SHA, SOURCE_SHA),
    }
    policy = {'bindings': [{
        'role': 'roles/iam.workloadIdentityUser',
        'members': [
            f'principalSet://iam.googleapis.com/projects/{PROJECT_NUMBER}'
            f'/locations/global/workloadIdentityPools/{POOL}'
            f'/attribute.repository_id/{ID}',
        ],
    }]}
    return cfg, github, provider, policy


def audit(*, settings_override=None, github_override=None,
          provider_override=None, iam_override=None, sha=SHA):
    s, g, p, i = snapshots()
    if settings_override:
        s.update(settings_override)
    if github_override:
        g.update(github_override)
    if provider_override:
        p.update(provider_override)
    if iam_override:
        i.update(iam_override)
    return review_observed_reader_wif(
        settings=s, reviewed_workflow_sha=sha,
        reviewed_source_commit_sha=SOURCE_SHA,
        observed_github_repo=g, observed_provider=p,
        observed_reader_iam_policy=i)


class PinnedGCPWIFTests(unittest.TestCase):
    def test_exact_sha_pinned_provider_is_manual_review_only(self):
        out = audit()
        self.assertEqual(
            out['status'], 'eligible_for_separate_manual_connection_review')
        self.assertTrue(out['workflow_sha_and_source_commit_pinned'])
        self.assertTrue(out['github_branch_is_unprotected'])
        self.assertFalse(out['checks']['branch_protection_verified'])
        self.assertTrue(out['manual_code_and_dependency_integrity_review_still_required'])
        self.assertFalse(out['actual_oidc_token_exchange_tested'])
        self.assertFalse(out['github_workflow_installed_or_run'])
        self.assertFalse(out['google_iam_changed'])
        self.assertFalse(out['additional_cost_guaranteed_zero'])
        summary = json.dumps(out)
        for value in (REPO, ID, OWNER_ID, PROVIDER, SA, SHA, SOURCE_SHA):
            self.assertNotIn(value, summary)

    def test_changes_to_workflow_commit_or_provider_expression_fail(self):
        for condition in (
            'assertion.repository_id=="12345678901"',
            snapshots()[2]['attributeCondition'].replace(
                "assertion.workflow_sha=='" + SHA + "'", ''),
            snapshots()[2]['attributeCondition'].replace(SHA, 'c'*40),
            snapshots()[2]['attributeCondition'].replace(SOURCE_SHA, 'c'*40),
            snapshots()[2]['attributeCondition'] + " || true",
        ):
            with self.subTest(condition=condition[:20]):
                result = audit(provider_override={'attributeCondition': condition})
                self.assertEqual(result['status'],
                                 'blocked_on_observed_trust_mismatch')
        with self.assertRaises(ValueError):
            audit(sha='invalid_sha')

    def test_repository_visibility_id_owner_and_branch_checks(self):
        for item in (
            {'visibility': 'public'}, {'id': 7},
            {'owner': {'id': 5}}, {'full_name': 'evil-user/repo'},
            {'archived': True}, {'default_branch': 'dev'},
        ):
            with self.subTest(item=item):
                result = audit(github_override=item)
                self.assertFalse(result['checks']['github_private_identity_matches'])
                self.assertEqual(result['status'],
                                 'blocked_on_observed_trust_mismatch')

    def test_issuer_mapping_and_liveness_checked(self):
        for field, value in (
            ('state', 'DELETED'),
            ('disabled', True),
            ('name', 'other/provider'),
            ('oidc', {'issuerUri': 'https://malicious.invalid'}),
            ('attributeMapping', {'google.subject': 'assertion.sub'}),
        ):
            with self.subTest(field=field):
                result = audit(provider_override={field: value})
                self.assertFalse(result['checks']['google_oidc_provider_exactly_pinned'])

    def test_missing_or_broad_principalset_iam_denied(self):
        for iam in (
            {'bindings': []},
            {'bindings': [{
                'role': 'roles/iam.workloadIdentityUser',
                'members': ['principalSet://iam.googleapis.com/projects/12/'
                            'locations/global/workloadIdentityPools/other/*'],
            }]},
            {'bindings': [{
                'role': 'roles/iam.workloadIdentityUser',
                'members': snapshots()[3]['bindings'][0]['members'] +
                           ['allUsers'],
            }]},
        ):
            with self.subTest(iam=str(iam)[:60]):
                result = audit(iam_override=iam)
                self.assertFalse(
                    result['checks']['dedicated_reader_iam_principalset_matches'])
                self.assertEqual(result['status'],
                                 'blocked_on_observed_trust_mismatch')

    def test_present_other_google_native_roles_are_not_asserted_safe(self):
        cfg, gh, provider, policy = snapshots()
        policy['bindings'].append({
            'role': 'roles/iam.serviceAccountTokenCreator',
            'members': ['serviceAccount:fake-colab-worker@example.invalid'],
        })
        out = review_observed_reader_wif(
            settings=cfg, reviewed_workflow_sha=SHA,
            reviewed_source_commit_sha=SOURCE_SHA,
            observed_github_repo=gh, observed_provider=provider,
            observed_reader_iam_policy=policy)
        self.assertFalse(out['all_google_reader_iam_grants_reviewed'])

    def test_invalid_preflight_settings_are_refused(self):
        for bad in (
            {'private_repo': False},
            {'production_spapi_identity_reused': True},
            {'scheduled': True},
            {'reader_service_account': 'spapi@example.invalid'},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                audit(settings_override=bad)

    def test_missing_or_malformed_observed_config_fails_closed(self):
        for observed in (None, [], 'provider'):
            with self.subTest(x=observed), self.assertRaises(ValueError):
                review_observed_reader_wif(
                    settings=settings(), reviewed_workflow_sha=SHA,
                    reviewed_source_commit_sha=SOURCE_SHA,
                    observed_github_repo=observed,
                    observed_provider=snapshots()[2],
                    observed_reader_iam_policy=snapshots()[3])

    def test_unverified_billing_or_google_share_blocks_even_with_exact_trust(self):
        for key in ('quota_and_billing_reviewed', 'reader_share_scope_reviewed',
                    'provider_review_completed', 'private_state_store_reviewed'):
            with self.subTest(key=key):
                output = audit(settings_override={key: False})
                self.assertEqual(
                    output['status'], 'blocked_on_external_configuration_review')
                self.assertFalse(output['actual_sheets_access_tested'])

    def test_branch_protection_is_separate_from_pinned_sha(self):
        result = audit(github_override={'default_branch_protected': True})
        self.assertTrue(result['checks']['branch_protection_verified'])
        self.assertFalse(result['github_branch_is_unprotected'])
        self.assertTrue(result['manual_code_and_dependency_integrity_review_still_required'])

    def test_pinned_condition_includes_all_expected_identity_claims(self):
        expected = expected_pinned_provider_condition(settings(), SHA, SOURCE_SHA)
        for part in (
            'repository_owner_id', 'repository_id', 'workflow_ref',
            'workflow_sha', 'sha', 'repository_visibility', 'runner_environment',
            'workflow_dispatch', 'refs/heads/main', SHA,
        ):
            self.assertIn(part, expected)


if __name__ == '__main__':
    unittest.main()
