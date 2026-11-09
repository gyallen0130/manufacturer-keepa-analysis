"""PRIVATE normalization of authenticated GitHub repository observations.

GitHub's connected get_repo returns 'repository_full_name' and owner.id as
an integer. The existing WIF reviewer consumes 'full_name' and a set of
immutable GitHub claims. This adapter converts only those exact observed
fields, rejects mismatches, and keeps all identifiers PRIVATE.

No GitHub/GCP network calls, file writes, OAuth, IAM edits or WIF testing.
The caller must fetch get_repo and branches/main independently from an
authenticated GitHub session. The resulting snapshot must be kept in the
same private execution environment as the gcloud WIF preflight.
"""
import re

_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_DIGITS = re.compile(r"^[1-9][0-9]{0,19}$")


def private_github_repo_wif_snapshot(*, repo, main_branch, expected_repo):
    """Build the exact PRIVATE GitHub payload expected by pinned_wif_audit.

    Not evidence of Cloud IAM, owner approval, correct Google scopes,
    code review, GitHub billing or an OIDC token exchange.
    """
    if (not isinstance(expected_repo, str)
            or not _REPO.fullmatch(expected_repo)
            or not isinstance(repo, dict)
            or not isinstance(main_branch, dict)):
        raise ValueError("verified private GitHub observations required")
    if repo.get("repository_full_name") != expected_repo:
        raise ValueError("unexpected GitHub repository identity")
    owner = repo.get("owner")
    if not isinstance(owner, dict):
        raise ValueError("GitHub owner identity unavailable")
    repo_id = repo.get("id")
    owner_id = owner.get("id")
    if (not isinstance(repo_id, str)
            or not _DIGITS.fullmatch(repo_id)
            or type(owner_id) is not int or not 0 < owner_id < 10**20
            or repo.get("visibility") != "private"
            or repo.get("default_branch") != "main"
            or repo.get("archived") is not False
            or owner.get("type") not in ("User", "Organization")
            or not isinstance(repo.get("permissions"), dict)
            or repo["permissions"].get("admin") is not True):
        raise ValueError("private admin-owned GitHub repository required")
    if (main_branch.get("name") != "main"
            or type(main_branch.get("protected")) is not bool):
        raise ValueError("verified main branch protection status required")
    return {
        "id": repo_id,
        "owner": {"id": owner_id},
        "full_name": expected_repo,
        "visibility": "private",
        "default_branch": "main",
        "archived": False,
        "default_branch_protected": main_branch["protected"],
    }


def redacted_github_wif_snapshot_summary(private_snapshot):
    """Safe booleans only. Never publish the private snapshot itself."""
    if not isinstance(private_snapshot, dict):
        raise ValueError("private GitHub snapshot required")
    if (set(private_snapshot) != {
            "id", "owner", "full_name", "visibility", "default_branch",
            "archived", "default_branch_protected"
        } or not isinstance(private_snapshot.get("owner"), dict)
            or set(private_snapshot["owner"]) != {"id"}
            or not isinstance(private_snapshot.get("id"), str)
            or not _DIGITS.fullmatch(private_snapshot["id"])
            or type(private_snapshot["owner"].get("id")) is not int
            or type(private_snapshot.get("default_branch_protected")) is not bool):
        raise ValueError("invalid private GitHub preflight snapshot")
    return {
        "schema": "redacted-github-wif-preflight-v1",
        "private_repository_observed": (
            private_snapshot["visibility"] == "private"),
        "main_branch_observed": (
            private_snapshot["default_branch"] == "main"),
        "branch_protection_enabled": (
            private_snapshot["default_branch_protected"]),
        "immutable_repo_and_owner_ids_present": True,
        "google_wif_provider_verified": False,
        "github_billing_reviewed_by_this_code": False,
        "oidc_exchange_performed": False,
        "production_connection_authorized": False,
    }
