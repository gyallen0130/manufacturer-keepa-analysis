"""Redacted read-only GitHub/Drive/WIF preflight for supplier metadata access.

Consumes independently authenticated snapshots gathered by the caller.
NEVER logs or emits repository IDs, Google IDs, emails, resource names,
price data, credentials, permissions JSON or code fingerprints.

IMPORTANT: This module cannot authenticate the snapshots or enable a
workflow. A passing review means eligible for a SEPARATE human decision,
not permission to deploy, run WIF, read cells, or incur charges.
"""
import re

READER_EMAIL = re.compile(
    r"^supplier-docs-reader@[a-z][a-z0-9-]{4,61}\.iam\.gserviceaccount\.com$"
)
_REPO_KEYS = frozenset(("repository_full_name", "visibility", "default_branch",
                       "archived", "id", "owner"))
_CHECK_ORDER = (
    "repo_is_expected_private",
    "main_branch_confirmed_unprotected_or_protected",
    "two_selected_files_verified",
    "dedicated_reader_shared_as_reader_on_all",
    "no_live_supplier_workflow_installed",
    "cloud_provider_and_reader_iam_verified",
    "cloud_oidc_source_sha_pins_verified",
    "github_billing_and_stop_control_reviewed",
    "independent_code_and_dependency_reviewed",
)


def assess_supplier_connection_preflight(
        *, repo_snapshot, branch_snapshot, selected_file_snapshots,
        expected_repo_name, expected_reader_email,
        live_workflow_absent, observed_cloud_wif_review=None,
        billing_and_stop_control_reviewed=False,
        code_and_dependency_reviewed=False):
    """Return redacted prerequisites; this function does not authorize actions.

    GitHub snapshots must come from independent get_repo & branches/main
    reads, and file permissions from the currently authenticated Drive owner.
    A projected permissions list can be incomplete; a missing Reader never
    counts as evidence of lack of access, just a BLOCKED check.

    An unprotected main branch can be considered for separate manual testing
    only if live Google-side OIDC checks include *both* reviewed workflow_sha
    and source sha, alongside an independent code/dependency review.
    """
    if (not isinstance(expected_repo_name, str)
            or not re.fullmatch(r"[\w.-]+/[\w.-]+", expected_repo_name)
            or not isinstance(expected_reader_email, str)
            or not READER_EMAIL.fullmatch(expected_reader_email)):
        raise ValueError("private target identity must be explicitly pinned")
    if (not isinstance(repo_snapshot, dict)
            or not isinstance(branch_snapshot, dict)
            or not isinstance(selected_file_snapshots, list)
            or len(selected_file_snapshots) != 2):
        raise ValueError("complete two-source read-only snapshots required")
    if (type(live_workflow_absent) is not bool
            or type(billing_and_stop_control_reviewed) is not bool
            or type(code_and_dependency_reviewed) is not bool):
        raise ValueError("explicit review flags required")

    owner = repo_snapshot.get("owner")
    repo_valid = (
        repo_snapshot.get("repository_full_name") == expected_repo_name
        and repo_snapshot.get("visibility") == "private"
        and repo_snapshot.get("default_branch") == "main"
        and repo_snapshot.get("archived") is False
        and isinstance(repo_snapshot.get("id"), str)
        and repo_snapshot["id"].isascii()
        and repo_snapshot["id"].isdecimal()
        and isinstance(owner, dict)
        and type(owner.get("id")) is int and owner["id"] > 0
        and owner.get("type") in ("User", "Organization")
    )
    branch_protection_known = (
        branch_snapshot.get("name") == "main"
        and type(branch_snapshot.get("protected")) is bool
    )
    branch_protected = (
        branch_protection_known and branch_snapshot["protected"] is True
    )
    file_checks = []
    distinct_ids = set()
    for info in selected_file_snapshots:
        valid = isinstance(info, dict)
        if not valid:
            file_checks.append(False)
            continue
        fid = info.get("id")
        mime = info.get("mime_type")
        permissions = info.get("permissions")
        if not isinstance(fid, str) or not fid:
            file_checks.append(False)
            continue
        distinct_ids.add(fid)
        valid = (
            mime == "application/vnd.google-apps.spreadsheet"
            and isinstance(permissions, list)
            and any(
                isinstance(p, dict)
                and p.get("type") == "user"
                and p.get("role") == "reader"
                and p.get("emailAddress") == expected_reader_email
                for p in permissions
            )
        )
        file_checks.append(valid)

    cloud = observed_cloud_wif_review
    cloud_checked = (
        isinstance(cloud, dict)
        and cloud.get("status") == "eligible_for_separate_manual_connection_review"
        and isinstance(cloud.get("checks"), dict)
        and cloud["checks"].get("github_private_identity_matches") is True
        and cloud["checks"].get("dedicated_reader_iam_principalset_matches") is True
        and cloud["checks"].get("google_oidc_provider_exactly_pinned") is True
        and cloud.get("actual_oidc_token_exchange_tested") is False
    )
    pinned = cloud_checked and cloud.get("workflow_sha_and_source_commit_pinned") is True
    checks = {
        "repo_is_expected_private": repo_valid,
        "main_branch_confirmed_unprotected_or_protected": branch_protection_known,
        "two_selected_files_verified": len(distinct_ids) == 2
            and all(isinstance(info, dict) and isinstance(info.get("id"), str)
                    and info.get("mime_type") == "application/vnd.google-apps.spreadsheet"
                    for info in selected_file_snapshots),
        "dedicated_reader_shared_as_reader_on_all": (
            len(distinct_ids) == 2 and all(file_checks)),
        "no_live_supplier_workflow_installed": live_workflow_absent,
        "cloud_provider_and_reader_iam_verified": cloud_checked,
        "cloud_oidc_source_sha_pins_verified": pinned,
        "github_billing_and_stop_control_reviewed": billing_and_stop_control_reviewed,
        "independent_code_and_dependency_reviewed": code_and_dependency_reviewed,
    }
    # A protected branch, or a separately verified cloud-side double SHA pin
    # plus an independent code review, is required BEFORE a manual test review.
    branch_risk_mitigated = branch_protected or (
        pinned and code_and_dependency_reviewed
    )
    blockers = [key for key in _CHECK_ORDER if not checks[key]]
    if branch_protection_known and not branch_risk_mitigated:
        blockers.append("unprotected_branch_without_reviewed_cloud_source_pins")
    ready = not blockers
    return {
        "schema_version": "supplier-connection-readonly-preflight-v1",
        "status": ("eligible_for_separate_owner_manual_test_review"
                   if ready else "blocked_no_live_connection"),
        "checks": checks,
        "branch_protected": branch_protected,
        "branch_risk_mitigated_by_verified_cloud_pins": (
            not branch_protected and branch_risk_mitigated),
        "remaining_checks": blockers,
        "real_google_oidc_exchange_performed_by_this_check": False,
        "real_google_file_version_read_performed_by_this_check": False,
        "billing_verified_by_this_code": False,
        "snapshots_authenticated_by_this_code": False,
        "manual_test_authorized": False,
        "cloud_iam_or_secrets_changed": False,
        "source_file_writes": 0,
    }
