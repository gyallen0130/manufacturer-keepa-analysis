"""Conservative no-network checks for the INACTIVE private WIF workflow example.

Approval preflight, not a full YAML security parser. It only recognizes a
reviewed template structure. The Python wheel hashes are now checked, but
real private repo, code trust, IAM and billing reviews remain mandatory.

No credentials, GitHub API, cloud API, purchases or workflow dispatch.
"""
import re

# SHA refs resolved from the official action tags as of 2026-11-08;
# referential pinning alone is not code integrity attestation.
ACTIONS = {
    "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",
    "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",
    "google-github-actions/auth": "7c6bc770dae815cd3e89ee6cdf493a5fab2cc093",
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
}
_MAX_WORKFLOW = 30000
_ACTION_LINE = re.compile(
    r"^\s*(?:-\s*)?uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@"
    r"([0-9a-f]{40})(?:\s+#.*)?$", re.MULTILINE
)
_ANY_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(.+)$", re.MULTILINE)


def review_private_workflow_template(text, *, dependency_lock=None):
    """Return anonymized structural gates; fail closed until hash-locked."""
    if not isinstance(text, str) or not 1 <= len(text) <= _MAX_WORKFLOW:
        raise ValueError("bounded private workflow template required")
    matches = list(_ACTION_LINE.finditer(text))
    all_uses = _ANY_USES.findall(text)
    actual = {name: ref for name, ref in (match.groups() for match in matches)}
    pinned = (
        len(matches) == len(all_uses) == len(ACTIONS)
        and len(actual) == len(ACTIONS)
        and actual == ACTIONS
    )
    # These are conservative string checks, not a general YAML parser.
    gated = (
        "\n  workflow_dispatch:" in text
        and "\n  pull_request:" not in text
        and "\n  push:" not in text
        and "\n  schedule:" not in text
        and "github.event.repository.private == true" in text
        and "github.event_name == 'workflow_dispatch'" in text
        and "github.ref == 'refs/heads/main'" in text
    )
    perms = (
        "\npermissions:\n  contents: read" in text
        and "      id-token: write" in text
        and "      contents: read" in text
        and "          persist-credentials: false" in text
    )
    encrypted = (
        "SUPPLIER_PRIVATE_RESULT_MODE: owner_encrypted_artifact" in text
        and "python -m supplier_docs.manual_sheet_probe" in text
        and "path: ${{ runner.temp }}/supplier-owner-encrypted-result.json" in text
        and "retention-days: 1" in text
        and "if-no-files-found: error" in text
        and not any(keyword in text for keyword in (
            "upload-artifact@v3", "pull_request_target",
            "GITHUB_TOKEN: ${{ secrets.", "--disable-verify",
            "SUPPLIER_PRIVATE_RESULT_MODE: plaintext",
        ))
    )
    from .private_dependency_lock import inspect_hashed_private_requirements
    lock_valid = False
    if dependency_lock is not None:
        try:
            inspect_hashed_private_requirements(dependency_lock)
            lock_valid = True
        except ValueError:
            lock_valid = False
    dependencies_locked = (
        lock_valid
        and "python -m pip install --require-hashes --only-binary=:all:" in text
        and "--no-deps" not in text
        and "-r manufacturer_checker/supplier_docs/approved-requirements-hashed.txt" in text
        and "pip install 'google-api-python-client>=" not in text
        and "pip install 'cryptography>=" not in text
    )
    checks = {
        "official_actions_full_commit_sha_pinned": pinned,
        "manual_private_only_structural_gate": gated,
        "least_privilege_workflow_permissions_present": perms,
        "encrypted_artifact_only_structural_gate": encrypted,
        "python_dependency_hash_lock_present": dependencies_locked,
    }
    return {
        "status": (
            "eligible_for_separate_live_review"
            if all(checks.values())
            else "blocked_on_workflow_or_dependency_review"
        ),
        "checks": checks,
        "real_private_repo_setup_verified": False,
        "real_google_wif_verified": False,
        "real_sheets_read_tested": False,
        "reviewed_commit_and_dependency_contents_attested": False,
        "automatic_workflow_enabled": False,
        "additional_cost_guaranteed_zero": False,
    }
