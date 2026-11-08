"""Read-only, fail-closed review of observed GitHub -> Google WIF trust.

Pure offline checks; NO Google Cloud API, GitHub API, token exchange, IAM
write, secret creation, workflow dispatch, or billing activity.

A reviewed 40-hex GITHUB workflow_sha claim can narrow trust even when
GitHub Free private-branch rulesets are unavailable. This DOES NOT attest
that the commit code, 3rd-party actions, dependency supply chain, or the
service account's other IAM bindings are safe. Actual GCP and GitHub
configuration must be read through an authorized separate process.

Required attribute mappings include all claims named in the condition.
Any edit to the reviewed workflow commit invalidates the pinned condition
until a new security review and separate human-approved Google IAM update.
"""
import hmac
import re

from .github_wif_review import plan_private_github_wif, _PROVIDER

_SHA = re.compile(r"^[0-9a-f]{40}$")
_ISSUER = "https://token.actions.githubusercontent.com"
_REQUIRED_MAPPING = {
    "google.subject": "assertion.sub",
    "attribute.repository_owner_id": "assertion.repository_owner_id",
    "attribute.repository_id": "assertion.repository_id",
    "attribute.ref": "assertion.ref",
    "attribute.event_name": "assertion.event_name",
    "attribute.workflow_ref": "assertion.workflow_ref",
    "attribute.workflow_sha": "assertion.workflow_sha",
    "attribute.repository_visibility": "assertion.repository_visibility",
    "attribute.runner_environment": "assertion.runner_environment",
}


def _expected_condition(plan_condition, reviewed_sha):
    return (
        plan_condition +
        " && assertion.workflow_sha=='" + reviewed_sha + "'" +
        " && assertion.repository_visibility=='private'" +
        " && assertion.runner_environment=='github-hosted'"
    )


def expected_pinned_provider_condition(settings, reviewed_workflow_sha):
    """Return private expected CEL condition, not proof of actual GCP state.

    Never put this output in public CI logs or commit it with real IDs.
    """
    plan = plan_private_github_wif(settings)
    if (not isinstance(reviewed_workflow_sha, str)
            or not _SHA.fullmatch(reviewed_workflow_sha)):
        raise ValueError("a separately reviewed immutable workflow commit is required")
    return _expected_condition(
        plan["private_required_provider_condition"], reviewed_workflow_sha)


def review_observed_reader_wif(
        *, settings, reviewed_workflow_sha,
        observed_github_repo, observed_provider, observed_reader_iam_policy):
    """Review externally supplied read-only snapshots; never authorize them.

    This checks an exact provider condition, GitHub repo identity/visibility,
    OIDC mappings, GitHub issuer and a repo-ID-bound principalSet grant.
    Reports redacted decision flags only: no sensitive repo ID, principal,
    project number, provider condition or token values in summary.
    """
    expected = expected_pinned_provider_condition(
        settings, reviewed_workflow_sha)
    if not all(isinstance(x, dict) for x in (
            observed_github_repo, observed_provider, observed_reader_iam_policy)):
        raise ValueError("complete read-only configuration snapshots required")

    private_repo = (
        str(observed_github_repo.get("id", "")) == settings["repository_id"]
        and isinstance(observed_github_repo.get("owner"), dict)
        and str(observed_github_repo["owner"].get("id", "")) == settings["owner_id"]
        and observed_github_repo.get("full_name") == settings["repository"]
        and observed_github_repo.get("visibility") == "private"
        and observed_github_repo.get("default_branch") == "main"
        and observed_github_repo.get("archived") is False
    )
    provider = observed_provider
    oidc = provider.get("oidc")
    mappings = provider.get("attributeMapping")
    provider_check = (
        provider.get("name") == settings["provider_resource"]
        and provider.get("state") == "ACTIVE"
        and provider.get("disabled") is False
        and isinstance(oidc, dict)
        and oidc.get("issuerUri") == _ISSUER
        and (oidc.get("allowedAudiences") in ([], None))
        and isinstance(mappings, dict)
        and all(mappings.get(k) == v
                for k, v in _REQUIRED_MAPPING.items())
        and isinstance(provider.get("attributeCondition"), str)
        and hmac.compare_digest(provider["attributeCondition"], expected)
    )

    resource = _PROVIDER.fullmatch(settings["provider_resource"])
    if resource is None:
        raise ValueError("invalid dedicated WIF provider resource")
    project_number, pool_id = resource.group(1), resource.group(2)
    exact_principal = (
        "principalSet://iam.googleapis.com/projects/" + project_number +
        "/locations/global/workloadIdentityPools/" + pool_id +
        "/attribute.repository_id/" + settings["repository_id"]
    )
    bindings = observed_reader_iam_policy.get("bindings")
    iam_found = False
    unexpected_external_principals = False
    if isinstance(bindings, list):
        for binding in bindings:
            if not isinstance(binding, dict):
                unexpected_external_principals = True
                continue
            if binding.get("role") == "roles/iam.workloadIdentityUser":
                members = binding.get("members")
                if not isinstance(members, list):
                    unexpected_external_principals = True
                    continue
                for member in members:
                    if member == exact_principal and "condition" not in binding:
                        iam_found = True
                    else:
                        # Dedicated Reader must not have unknown external WIF
                        # principals. Existing non-WIF Google-native bindings
                        # still require separate human review.
                        unexpected_external_principals = True
    else:
        unexpected_external_principals = True

    checks = {
        "github_private_identity_matches": private_repo,
        "google_oidc_provider_exactly_pinned": provider_check,
        "dedicated_reader_iam_principalset_matches": (
            iam_found and not unexpected_external_principals),
        "branch_protection_verified": (
            observed_github_repo.get("default_branch_protected") is True),
    }
    trust_checks_pass = all((
        checks["github_private_identity_matches"],
        checks["google_oidc_provider_exactly_pinned"],
        checks["dedicated_reader_iam_principalset_matches"],
    ))
    # Branch protection is valuable but for Free private repos the
    # approved workflow SHA is a separate cloud-side pin, NOT a replacement
    # for full code integrity review. Never claim this is deployed.
    return {
        "status": (
            "eligible_for_separate_manual_connection_review"
            if trust_checks_pass else "blocked_on_observed_trust_mismatch"),
        "checks": checks,
        "workflow_sha_pinned_to_reviewed_commit": provider_check,
        "github_branch_is_unprotected": (
            observed_github_repo.get("default_branch_protected") is False),
        "manual_code_and_dependency_integrity_review_still_required": True,
        "observed_snapshots_independently_authenticated_by_code": False,
        "all_google_reader_iam_grants_reviewed": False,
        "actual_oidc_token_exchange_tested": False,
        "actual_sheets_access_tested": False,
        "github_workflow_installed_or_run": False,
        "google_iam_changed": False,
        "additional_cost_guaranteed_zero": False,
    }
