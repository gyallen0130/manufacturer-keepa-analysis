"""Offline preflight for a private GitHub Actions + reader-only WIF option.

This module DOES NOT inspect the user's live Google Cloud IAM, authorize a
GitHub workflow, install actions, or touch supplier documents. The output
identifies requirements that a future *human-reviewed* setup must satisfy.

No service account key JSON, production Amazon SP-API identity, new Cloud Run,
Secret Manager or scheduled job is required by the *proposed architecture*.
Actual GitHub minutes, Google API quotas and credentials remain unverified.
"""
import re

_PROVIDER = re.compile(
    r'^projects/([0-9]{6,20})/locations/global/'
    r'workloadIdentityPools/([a-z][a-z0-9-]{2,31})/'
    r'providers/([a-z][a-z0-9-]{2,31})$'
)
_SA = re.compile(
    r'^supplier-docs-reader@[a-z][a-z0-9-]{4,61}\.iam\.gserviceaccount\.com$'
)
_PRIVATE_ID = re.compile(r'^[0-9]{1,20}$')
_REPO = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')

REQUIRED = frozenset({
    'private_repo', 'repository', 'repository_id', 'owner_id',
    'branch_ref', 'workflow_ref', 'event_name',
    'reader_service_account', 'provider_resource',
    'provider_review_completed', 'reader_share_scope_reviewed',
    'quota_and_billing_reviewed', 'private_state_store_reviewed',
    'secret_json_keys_present', 'live_access_enabled', 'scheduled',
    'public_artifacts_enabled', 'production_spapi_identity_reused',
})


def plan_private_github_wif(settings):
    """Fail-closed plan to keep price and Google Drive access bounded.

    This function never grants WIF or GitHub permissions. The provider MUST
    independently enforce the suggested condition, mapping the immutable
    GitHub repository and owner IDs; workflow YAML conditions are not an
    alternative to restricting cloud-side trust.
    """
    if not isinstance(settings, dict) or set(settings) != REQUIRED:
        raise ValueError('invalid private GitHub WIF preflight')
    bool_keys = (
        'private_repo', 'provider_review_completed',
        'reader_share_scope_reviewed', 'quota_and_billing_reviewed',
        'private_state_store_reviewed', 'secret_json_keys_present',
        'live_access_enabled', 'scheduled', 'public_artifacts_enabled',
        'production_spapi_identity_reused',
    )
    if any(type(settings[key]) is not bool for key in bool_keys):
        raise ValueError('explicit preflight booleans required')

    repo, repo_id, owner_id = (
        settings['repository'], settings['repository_id'],
        settings['owner_id'])
    if (not isinstance(repo, str) or not _REPO.fullmatch(repo)
            or any(segment in ('.', '..') for segment in repo.split('/'))
            or not isinstance(repo_id, str)
            or not _PRIVATE_ID.fullmatch(repo_id)
            or not isinstance(owner_id, str)
            or not _PRIVATE_ID.fullmatch(owner_id)):
        raise ValueError('immutable GitHub repository/owner identifiers required')
    if settings['branch_ref'] != 'refs/heads/main':
        raise ValueError('only the explicitly reviewed main branch may be authorized')
    expected_ref = repo + '/.github/workflows/supplier-readonly.yml@refs/heads/main'
    if settings['workflow_ref'] != expected_ref or settings['event_name'] != 'workflow_dispatch':
        raise ValueError('only the named manual workflow may use OIDC')
    provider = settings['provider_resource']
    match = _PROVIDER.fullmatch(provider) if isinstance(provider, str) else None
    if not match or 'spapi' in provider.lower():
        raise ValueError('dedicated GitHub WIF provider resource required')
    sa = settings['reader_service_account']
    if not isinstance(sa, str) or not _SA.fullmatch(sa):
        raise ValueError('supplier-only reader identity required')
    if (not settings['private_repo'] or settings['secret_json_keys_present']
            or settings['scheduled'] or settings['live_access_enabled']
            or settings['public_artifacts_enabled']
            or settings['production_spapi_identity_reused']):
        raise ValueError('unsafe private-runner deployment proposal')

    # Both conditions must be applied on the GOOGLE CLOUD provider. They do
    # not become active just by returning this string from the preflight.
    required_cloud_condition = (
        "assertion.repository_owner_id=='" + owner_id + "' && "
        "assertion.repository_id=='" + repo_id + "' && "
        "assertion.ref=='refs/heads/main' && "
        "assertion.event_name=='workflow_dispatch' && "
        "assertion.workflow_ref=='" + expected_ref + "'"
    )
    review_complete = all(settings[key] for key in (
        'provider_review_completed', 'reader_share_scope_reviewed',
        'quota_and_billing_reviewed', 'private_state_store_reviewed'))
    return {
        # This condition and private IDs must be inspected only in PRIVATE
        # project documentation, never print them in public CI.
        'private_required_provider_condition': required_cloud_condition,
        'summary': {
            'status': ('eligible_for_separate_manual_test_review'
                       if review_complete else 'blocked_on_external_configuration_review'),
            'private_repository_required': True,
            'manual_dispatch_only': True,
            'uses_service_account_json_keys': False,
            'requires_immutable_github_claims': True,
            'cloud_side_provider_condition_verified_by_this_check': False,
            'repository_owner_and_repo_ids_verified_by_this_check': False,
            'github_minutes_and_api_quota_checked_by_this_check': False,
            'private_persistent_state_verified_by_this_check': False,
            'new_paid_service_provisioned': False,
            'real_workflow_triggered': False,
            'cloud_iam_changes': 0,
            'scheduler_jobs_created': 0,
            'additional_cost_guaranteed_zero': False,
        },
    }
