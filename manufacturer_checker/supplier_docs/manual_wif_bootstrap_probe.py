"""Read-only FIRST-STEP WIF/Reader presence check for a trusted Cloud Shell.

Unlike the strict pinned audit, this preliminary check does not require a
reviewed workflow SHA (the private workflow is not deployed). It only tests
whether the dedicated Google provider and Reader policy are readable.
It cannot prove that WIF grants are safe, that GitHub may authenticate, or
that a Google file may be accessed. NEVER use this as a deployment gate.

Only two prevalidated gcloud describe/get-iam-policy commands may execute.
No Cloud API writes, Sheets reads, OIDC token exchange, workflow dispatch,
credentials creation, or raw IAM JSON output. Identifiers belong in the
operator's PRIVATE environment, never in public Github or chat logs.
"""
import argparse
import json
import os
import subprocess

from .gcloud_wif_readback import (
    _MAX_BYTES, _default_execute, build_readonly_gcloud_commands,
)

_ISSUER = "https://token.actions.githubusercontent.com"


def inspect_wif_bootstrap_readonly(*, provider_resource, reader_service_account,
                                   owner_approved_readonly=False, executor=None):
    """Anonymous checks. These are preliminary evidence, NOT permission."""
    if owner_approved_readonly is not True:
        raise PermissionError("explicit read-only owner confirmation required")
    commands = build_readonly_gcloud_commands({
        "provider_resource": provider_resource,
        "reader_service_account": reader_service_account,
    })
    execute = _default_execute if executor is None else executor
    if not callable(execute):
        raise ValueError("read-only local gcloud executor required")

    observed = []
    for argv in commands:
        try:
            response = execute(argv)
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError("read-only Google Cloud inspection unavailable") from None
        if (getattr(response, "returncode", None) != 0
                or not isinstance(getattr(response, "stdout", None), str)
                or not 1 <= len(response.stdout) <= _MAX_BYTES):
            # Do not log command args, stderr, or Google resource paths.
            raise ValueError("read-only Google Cloud inspection unavailable")
        try:
            decoded = json.loads(response.stdout)
        except (ValueError, UnicodeError):
            raise ValueError("invalid private Google Cloud response") from None
        if not isinstance(decoded, dict):
            raise ValueError("invalid private Google Cloud response")
        observed.append(decoded)

    provider, policy = observed
    oidc = provider.get("oidc")
    attrs = provider.get("attributeMapping")
    required_claims = (
        "attribute.repository_id", "attribute.repository_owner_id",
        "attribute.workflow_sha", "attribute.sha",
    )
    bindings = policy.get("bindings")
    checks = {
        "provider_metadata_readable": provider.get("name") == provider_resource,
        "provider_reports_active": provider.get("state") == "ACTIVE",
        "provider_reports_not_disabled": provider.get("disabled") is False,
        "github_oidc_issuer_observed": (
            isinstance(oidc, dict) and oidc.get("issuerUri") == _ISSUER),
        "required_claim_mappings_present": (
            isinstance(attrs, dict)
            and all(isinstance(attrs.get(k), str) and attrs[k].strip()
                    for k in required_claims)),
        "cloud_reader_policy_readable": isinstance(bindings, list),
        "some_workload_identity_user_grant_present": (
            isinstance(bindings, list)
            and any(isinstance(b, dict)
                    and b.get("role") == "roles/iam.workloadIdentityUser"
                    and isinstance(b.get("members"), list)
                    and len(b["members"]) > 0
                    for b in bindings)),
    }
    return {
        "schema": "manual-readonly-gcloud-wif-bootstrap-v1",
        "status": "bootstrap_evidence_collected_not_approved",
        "checks": checks,
        "strict_wif_provider_condition_verified": False,
        "exact_repository_and_sha_pinning_verified": False,
        "reader_iam_grants_audited": False,
        "github_actions_billing_verified": False,
        "wif_oidc_token_exchange_performed": False,
        "source_sheet_access_tested": False,
        "production_connection_authorized": False,
        "cloud_iam_writes": 0,
    }


def main(argv=None, *, environ=None, executor=None, output=None):
    parser = argparse.ArgumentParser(
        description="Read only: inspect supplier Google WIF and Reader existence")
    parser.add_argument("--confirm-readonly", action="store_true")
    args = parser.parse_args(argv)
    writer = print if output is None else output
    env = os.environ if environ is None else environ
    try:
        result = inspect_wif_bootstrap_readonly(
            provider_resource=env.get("SUPPLIER_WIF_PROVIDER"),
            reader_service_account=env.get("SUPPLIER_READER_SA"),
            owner_approved_readonly=args.confirm_readonly,
            executor=executor,
        )
    except Exception:
        writer(json.dumps({
            "schema": "manual-readonly-gcloud-wif-bootstrap-v1",
            "status": "blocked_cloud_bootstrap_not_verified",
            "production_connection_authorized": False,
        },sort_keys=True))
        return 1
    writer(json.dumps(result, sort_keys=True))
    return 0 if all(result["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
