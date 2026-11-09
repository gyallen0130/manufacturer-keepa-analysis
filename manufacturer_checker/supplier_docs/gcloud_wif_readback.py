"""Explicit, read-only gcloud snapshot inspection for manual WIF setup review.

Never run by GitHub Actions or as a scheduled task. Does not authenticate,
request Google OIDC tokens, grant IAM roles, access Sheets, create secrets,
or modify a repository. Only two gcloud *describe/get-iam-policy* operations
can execute, and only after explicit opt-in on a trusted LOCAL machine.

The gcloud CLI executable must be installed and already authenticated to a
suitable least-privilege account by the operator. Provider and IAM readback
contents stay in memory; no subprocess output or account identifiers are
printed to stdout/stderr. The caller must source the GitHub repo metadata
from an independently authenticated GitHub read-only API.
"""
import json
import re
import subprocess

from .github_wif_review import _PROVIDER, _SA
from .pinned_wif_audit import review_observed_reader_wif

_MAX_BYTES = 160_000
_GCLOUD = "gcloud"


def build_readonly_gcloud_commands(settings):
    """Only two fixed list-argv commands with validated nonsecret identifiers."""
    if not isinstance(settings, dict):
        raise ValueError("private WIF settings are required")
    ref = settings.get("provider_resource")
    sa = settings.get("reader_service_account")
    match = _PROVIDER.fullmatch(ref) if isinstance(ref, str) else None
    if not match or not isinstance(sa, str) or not _SA.fullmatch(sa):
        raise ValueError("dedicated provider and reader service account required")
    project_number, pool, provider = match.groups()
    return (
        [
            _GCLOUD, "iam", "workload-identity-pools", "providers",
            "describe", provider, "--workload-identity-pool=" + pool,
            "--location=global", "--project=" + project_number, "--format=json",
        ],
        [
            _GCLOUD, "iam", "service-accounts", "get-iam-policy", sa,
            "--project=" + project_number, "--format=json",
        ],
    )


def _default_execute(argv):
    return subprocess.run(
        argv, shell=False, capture_output=True, text=True, timeout=20,
        check=False)


def inspect_readonly_cloud_wif(
        *, settings, github_repo_snapshot, reviewed_workflow_sha,
        reviewed_source_commit_sha, owner_approved_readonly=False,
        executor=None):
    """Return an anonymous IAM readiness review; do not persist raw snapshots.

    Owner approval must precede *any* Cloud API access. This flag does not
    grant credentials or authorize a production workflow deployment.
    """
    if owner_approved_readonly is not True:
        raise PermissionError("explicit owner approval for gcloud reads required")
    if not isinstance(github_repo_snapshot, dict):
        raise ValueError("authenticated GitHub metadata snapshot required")
    commands = build_readonly_gcloud_commands(settings)
    # Preflight both SHA pins and other config before making external requests.
    from .pinned_wif_audit import expected_pinned_provider_condition
    expected_pinned_provider_condition(
        settings, reviewed_workflow_sha, reviewed_source_commit_sha)
    run = _default_execute if executor is None else executor
    response = []
    for command in commands:
        try:
            result = run(command)
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError("cloud read-only inspection failed") from None
        if (getattr(result, "returncode", None) != 0
                or not isinstance(getattr(result, "stdout", None), str)
                or not 1 <= len(result.stdout) <= _MAX_BYTES):
            # gcloud stderr may contain account information or provider paths.
            raise ValueError("cloud read-only inspection failed")
        try:
            item = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise ValueError("invalid cloud read-only response") from None
        if not isinstance(item, dict):
            raise ValueError("invalid cloud read-only response")
        response.append(item)
    # Never include API JSON, gcloud stderr, project IDs or source codes
    # in the result or normal logs.
    return review_observed_reader_wif(
        settings=settings,
        reviewed_workflow_sha=reviewed_workflow_sha,
        reviewed_source_commit_sha=reviewed_source_commit_sha,
        observed_github_repo=github_repo_snapshot,
        observed_provider=response[0],
        observed_reader_iam_policy=response[1])
