"""Owner-operated Google WIF preflight (READ ONLY; no live workflow).

Run only on a trusted local machine/Cloud Shell after explicit review.
No login, token exchange, IAM edits, Sheets reads, secrets writes, workflow
dispatch, repository writes, or paid-resource provisioning.

Input JSON is private local configuration. All normal output is a redacted
decision, never a provider/SA/repository identifier or raw API response.
"""
import argparse
import json
import os
from pathlib import Path
import stat
import sys

from .gcloud_wif_readback import inspect_readonly_cloud_wif

_MAX_JSON_BYTES = 16_384


def _load_private_object(path):
    """Load a small non-symlink local JSON file; never print its content."""
    if not isinstance(path, str) or not path:
        raise ValueError("local JSON input required")
    target = Path(path).expanduser()
    if not target.is_absolute():
        raise ValueError("absolute JSON input path required")
    info = target.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError("regular non-symlink JSON input required")
    if not 1 <= info.st_size <= _MAX_JSON_BYTES:
        raise ValueError("private JSON input exceeds size limit")
    if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("private JSON input needs chmod 600")
    with target.open("rb") as source:
        raw = source.read(_MAX_JSON_BYTES + 1)
    if not 1 <= len(raw) <= _MAX_JSON_BYTES:
        raise ValueError("private JSON input exceeds size limit")
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise ValueError("invalid private JSON input") from None
    if not isinstance(obj, dict):
        raise ValueError("JSON object required")
    return obj


def run_owner_preflight(argv=None, *, inspector=None, output=None, errors=None):
    """Emit only anonymous checks. Returning 0 DOES NOT authorize production."""
    output = sys.stdout if output is None else output
    errors = sys.stderr if errors is None else errors
    parser = argparse.ArgumentParser(
        description="Read-only WIF/IAM review; never starts GitHub Actions.")
    parser.add_argument("--settings-file", required=True)
    parser.add_argument("--github-snapshot-file", required=True)
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--confirm-readonly", action="store_true")
    args = parser.parse_args(argv)

    # Fail before opening even a local file if the operator did not opt in.
    if not args.confirm_readonly:
        errors.write(
            "Not run. Explicit --confirm-readonly required; no API calls.\n")
        return 2
    try:
        settings = _load_private_object(args.settings_file)
        github_snapshot = _load_private_object(args.github_snapshot_file)
        inspect = inspect_readonly_cloud_wif if inspector is None else inspector
        result = inspect(
            settings=settings,
            github_repo_snapshot=github_snapshot,
            reviewed_workflow_sha=args.workflow_sha,
            reviewed_source_commit_sha=args.source_sha,
            owner_approved_readonly=True,
        )
        report = {
            "status": result["status"],
            "checks": result["checks"],
            "actual_oidc_token_exchange_tested": False,
            "actual_sheets_access_tested": False,
            "production_connection_authorized": False,
            "additional_cost_guaranteed_zero": False,
        }
        output.write(json.dumps(report, sort_keys=True, ensure_ascii=True) + "\n")
        return 0 if result["status"] == (
            "eligible_for_separate_manual_connection_review") else 1
    except Exception:
        # Neither subprocess stderr nor local JSON paths/values are disclosed.
        errors.write(
            "Read-only preflight could not verify trust; no details emitted.\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(run_owner_preflight())
