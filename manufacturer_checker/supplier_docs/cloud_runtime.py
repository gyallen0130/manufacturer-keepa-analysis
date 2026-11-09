"""Fail-closed, OFFLINE configuration checks for isolated supplier Cloud Run jobs.

This only validates a proposed PRIVATE deployment manifest. It never calls
Google Cloud, creates resources, launches jobs or changes permissions. It must
not be wired into existing Amazon SP-API infrastructure by default.
"""
import re

REQUIRED = frozenset({
    'project_id', 'region', 'job_name', 'worker_sa', 'reader_sa',
    'review_sa', 'scheduler_sa', 'state_bucket', 'review_bucket',
    'state_encryption_secret', 'journal_encryption_secret',
    'review_signing_secret', 'mode', 'schedule_enabled',
    'max_parallelism', 'max_retries', 'raw_data_logging',
    'automatic_review', 'recursive_drive_scan',
})
_PROJECT = re.compile(r'^[a-z][a-z0-9-]{4,61}[a-z0-9]$')
_REGION = re.compile(r'^[a-z]+-[a-z]+\d+$')
_SAFE_NAME = re.compile(r'^[a-z][a-z0-9-]{2,62}$')
_BUCKET = re.compile(r'^[a-z0-9][a-z0-9.-]{5,61}[a-z0-9]$')
_SECRETS = ('state_encryption_secret', 'journal_encryption_secret',
            'review_signing_secret')


def validate_supplier_cloud_runtime(manifest):
    """Return an anonymous, inert assessment of one isolation proposal.

    Accept only an independent supplier-docs worker and its distinct identities.
    The reader SA may already exist for Colab; worker/reviewer/scheduler SAs
    are separate *future* resources, NOT implicitly created by this check.
    In dry-run mode all scheduler, automatic review and raw logs stay off.
    """
    if not isinstance(manifest, dict) or set(manifest) != REQUIRED:
        raise ValueError('invalid private deployment manifest structure')
    project = manifest['project_id']
    if not isinstance(project, str) or not _PROJECT.fullmatch(project):
        raise ValueError('invalid isolated project reference')
    region = manifest['region']
    if not isinstance(region, str) or not _REGION.fullmatch(region):
        raise ValueError('invalid proposed Cloud Run region')
    job = manifest['job_name']
    if (not isinstance(job, str) or not _SAFE_NAME.fullmatch(job)
            or not job.startswith('supplier-docs-') or 'spapi' in job):
        raise ValueError('unsafe proposed job name')
    bucket = manifest['state_bucket']
    if (not isinstance(bucket, str) or not _BUCKET.fullmatch(bucket)
            or not bucket.startswith('supplier-docs-state-')):
        raise ValueError('state bucket must be supplier-specific')

    review_bucket = manifest['review_bucket']
    if (not isinstance(review_bucket, str)
            or not _BUCKET.fullmatch(review_bucket)
            or not review_bucket.startswith('supplier-docs-review-')
            or review_bucket == bucket):
        raise ValueError('separate supplier review bucket required')

    identities = []
    for key in ('worker_sa', 'reader_sa', 'review_sa', 'scheduler_sa'):
        value = manifest[key]
        suffix = '@' + project + '.iam.gserviceaccount.com'
        if (not isinstance(value, str) or not value.endswith(suffix)
                or not value.startswith('supplier-docs-')
                or not _SAFE_NAME.fullmatch(value[:-len(suffix)])):
            raise ValueError('invalid dedicated service identity')
        identities.append(value)
    if len(set(identities)) != 4:
        raise ValueError('separate worker, reader, reviewer and trigger identities required')
    for prefix, sa in [('worker', identities[0]), ('reader', identities[1]),
                       ('review', identities[2]), ('trigger', identities[3])]:
        if not sa.startswith('supplier-docs-' + prefix + '@'):
            raise ValueError('service identity has incompatible purpose')

    secret_names = []
    for key in _SECRETS:
        value = manifest[key]
        prefix = 'projects/' + project + '/secrets/'
        if not isinstance(value, str) or not value.startswith(prefix):
            raise ValueError('secret must belong to the proposed project')
        tail = value[len(prefix):]
        parts = tail.split('/versions/')
        if (len(parts) != 2 or not parts[1].isdigit() or int(parts[1]) <= 0
                or not _SAFE_NAME.fullmatch(parts[0])
                or not parts[0].startswith('supplier-docs-')):
            raise ValueError('use a version-pinned supplier-only secret')
        secret_names.append(parts[0])
    if len(set(secret_names)) != 3:
        raise ValueError('state, journal and review signing secrets must differ')

    for flag in ('schedule_enabled', 'raw_data_logging',
                 'automatic_review', 'recursive_drive_scan'):
        if type(manifest[flag]) is not bool or manifest[flag]:
            raise ValueError('dry-run environment must not enable live actions')
    if manifest['mode'] != 'dry_run':
        raise ValueError('runtime may not be deployed automatically')
    if type(manifest['max_parallelism']) is not int or manifest['max_parallelism'] != 1:
        raise ValueError('single writer is mandatory for the current local state design')
    if type(manifest['max_retries']) is not int or manifest['max_retries'] != 0:
        raise ValueError('automatic Cloud Run retries disabled until proven idempotent')

    # Do not return any identifiers, service account addresses, secret names
    # or other private configuration values to public CI or ordinary logs.
    return {
        'configuration_valid': True,
        'operation': 'offline_preflight_only',
        'separate_identities': 4,
        'separate_state_and_review_buckets': True,
        'separate_version_pinned_secrets': 3,
        'scheduler_enabled': False,
        'automatic_review_enabled': False,
        'raw_source_logging_enabled': False,
        'recursive_drive_scan_enabled': False,
        'max_parallelism': 1,
        'max_retries': 0,
        'cloud_changes_made': False,
    }
