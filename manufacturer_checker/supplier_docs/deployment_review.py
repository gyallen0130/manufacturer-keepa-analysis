"""Offline-only least-privilege IAM review proposal for supplier-docs.

No Google Cloud calls, resource creation, IAM writes, or secret access.
The returned binding list is PRIVATE and NOT safe for public logs because it
contains service-account identities and resource names. Return summary alone
for routine reporting. These are proposals, not proof of active permissions.

An independent human-admin review is required before any IAM grant.
"""
from .cloud_runtime import validate_supplier_cloud_runtime


def _secret_resource(versioned):
    # IAM binding targets the secret, not its individual version.
    return versioned.split('/versions/', 1)[0]


def plan_supplier_iam(manifest):
    """Propose exact resource-level roles for an isolated future deployment.

    The review service can verify and sign receipts; the worker intentionally
    has no access to the review signing secret or review journal bucket.
    This DOES NOT solve verified receipt handoff and atomic state advancement:
    that architectural gap stays a deployment blocker, not an auto-grant.
    """
    validate_supplier_cloud_runtime(manifest)
    project = manifest['project_id']
    region = manifest['region']
    job = manifest['job_name']

    def row(who, role, scope, purpose, *, deferred=False):
        return {
            'principal': manifest[who], 'role': role, 'resource': scope,
            'purpose': purpose, 'deferred': deferred,
        }

    state_bucket = 'projects/_/buckets/' + manifest['state_bucket']
    review_bucket = 'projects/_/buckets/' + manifest['review_bucket']
    reader_sa = ('projects/' + project + '/serviceAccounts/'
                 + manifest['reader_sa'])
    job_path = f'projects/{project}/locations/{region}/jobs/{job}'
    bindings = [
        row('worker_sa', 'roles/iam.serviceAccountTokenCreator', reader_sa,
            'short_lived_reader_impersonation'),
        row('worker_sa', 'roles/storage.objectUser', state_bucket,
            'encrypted_inventory_only'),
        row('worker_sa', 'roles/secretmanager.secretAccessor',
            _secret_resource(manifest['state_encryption_secret']),
            'inventory_encryption_key_only'),
        row('review_sa', 'roles/storage.objectViewer', state_bucket,
            'read_inventory_for_review_only'),
        row('review_sa', 'roles/storage.objectUser', review_bucket,
            'encrypted_review_journal_only'),
        row('review_sa', 'roles/secretmanager.secretAccessor',
            _secret_resource(manifest['journal_encryption_secret']),
            'review_journal_encryption_key_only'),
        row('review_sa', 'roles/secretmanager.secretAccessor',
            _secret_resource(manifest['review_signing_secret']),
            'sign_review_receipts_only'),
        row('scheduler_sa', 'roles/run.invoker', job_path,
            'future_scheduled_job_invocation_only', deferred=True),
    ]
    return {
        'private_bindings': bindings,
        'summary': {
            'status': 'offline_draft_not_applied',
            'permission_grants_performed': 0,
            'bindings_proposed': len(bindings),
            'deferred_bindings': 1,
            'no_project_wide_roles': True,
            'separate_state_and_review_buckets': True,
            'worker_cannot_read_review_signing_secret': True,
            'worker_cannot_read_review_journal': True,
            'blocked_until_human_approval': True,
            'blocked_until_safe_review_handoff_and_recovery': True,
            'blocked_until_drive_folder_scope_approved': True,
        },
    }


def validate_exact_iam_proposal(manifest, candidate_bindings):
    """Reject privileged drift or missing constraints before applying IAM.

    Do not call this a production permission audit: it validates a supplied
    PROPOSAL only. Actual cloud IAM state requires a separate authenticated
    read-only inspection once deployment is explicitly authorized.
    """
    expected = plan_supplier_iam(manifest)['private_bindings']
    if (not isinstance(candidate_bindings, list)
            or len(candidate_bindings) != len(expected)
            or candidate_bindings != expected):
        raise ValueError('IAM proposal differs from exact bounded plan')
    return {'valid_proposal': True, 'changes_applied': False,
            'requires_human_approval': True}
