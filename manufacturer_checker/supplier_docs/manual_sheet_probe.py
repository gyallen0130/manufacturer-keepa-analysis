"""Manual GitHub Actions -> Google Sheets reader, PRIVATE repositories ONLY.

No scheduled events, PR runs, local implicit-user credentials, Drive
browsing, files, status uploads or production integrations are allowed.
The runner logs ONLY anonymized counts. Optional detail delivery seals all
private inspection values to an owner-pinned X25519 public key BEFORE saving
the encrypted artifact in RUNNER_TEMP. No plaintext artifacts are written.

ENV is NOT an authentication mechanism: a Google-side WIF provider condition
using immutable repo/owner IDs and exact workflow claims MUST be independently
verified before this entrypoint is enabled in a private repo.
"""
import json
import os
import re
import sys

from .on_demand_reader import (
    inspect_manual_approved_sheets, validate_manual_sheet_manifest,
)

MANIFEST_ENV = 'SUPPLIER_READ_MANIFEST_JSON'
_MAX_ENV_LENGTH = 16000
_REPO = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
_ID = re.compile(r'^[0-9]{1,20}$')


def validate_private_manual_runner(environ):
    """Deny accidental public, scheduled, pull-request, or local credential runs.

    These ENV checks are a defense in depth only; workflow and cloud IAM
    bindings (not controlled here) are the real access security boundary.
    """
    if not hasattr(environ, 'get'):
        raise ValueError('invalid runner environment')
    repo = environ.get('GITHUB_REPOSITORY')
    if (environ.get('GITHUB_ACTIONS') != 'true'
            or environ.get('SUPPLIER_REPO_PRIVATE') != 'true'
            or environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or environ.get('GITHUB_REF') != 'refs/heads/main'
            or not isinstance(repo, str)
            or not _REPO.fullmatch(repo)
            or not isinstance(environ.get('GITHUB_REPOSITORY_ID'), str)
            or not _ID.fullmatch(environ.get('GITHUB_REPOSITORY_ID'))
            or not isinstance(environ.get('GITHUB_REPOSITORY_OWNER_ID'), str)
            or not _ID.fullmatch(environ.get('GITHUB_REPOSITORY_OWNER_ID'))
            or environ.get('GITHUB_WORKFLOW_REF') !=
            repo + '/.github/workflows/supplier-readonly.yml@refs/heads/main'
            or not environ.get('GOOGLE_APPLICATION_CREDENTIALS')):
        raise ValueError('unreviewed or non-private GitHub runner context')
    raw = environ.get(MANIFEST_ENV)
    if not isinstance(raw, str) or not 0 < len(raw) <= _MAX_ENV_LENGTH:
        raise ValueError('private approved target manifest missing')
    try:
        manifest = json.loads(raw)
    except ValueError:
        raise ValueError('invalid private approved target manifest') from None
    # Validate entire manifest before creating an authenticated Google client.
    validate_manual_sheet_manifest(manifest)
    return manifest



def validate_encrypted_owner_delivery(environ):
    """Require complete owner encryption config BEFORE Google API calls.

    The fingerprint is an owner-pinned trust value. Environ alone does not
    prove key ownership; the owner must validate it independently.
    """
    mode = environ.get('SUPPLIER_PRIVATE_RESULT_MODE', 'summary_only')
    if mode == 'summary_only':
        return None
    if mode != 'owner_encrypted_artifact':
        raise ValueError('unsupported private result handling mode')
    from .private_result_envelope import HEX_SHA256, _decode
    import hashlib
    import hmac
    key = environ.get('SUPPLIER_RECIPIENT_PUBLIC_KEY_B64')
    fingerprint = environ.get('SUPPLIER_RECIPIENT_KEY_FINGERPRINT_SHA256')
    root = environ.get('RUNNER_TEMP')
    if (not isinstance(fingerprint, str)
            or not HEX_SHA256.fullmatch(fingerprint)
            or not isinstance(root, str) or not root):
        raise ValueError('owner encryption configuration incomplete')
    public_key = _decode(key, size=32)
    if not hmac.compare_digest(
            hashlib.sha256(public_key).hexdigest(), fingerprint):
        raise ValueError('untrusted owner recipient key')
    # Avoid touching any files here. Full path review occurs in artifact sink.
    return {'recipient_public_key_b64': key,
            'trusted_fingerprint_sha256': fingerprint,
            'runner_temp': root}

def main(*, environ=None, service_factory=None, stdout=None, stderr=None):
    """Read-only manual probe; never prints secret values or traceback details."""
    output = sys.stdout if stdout is None else stdout
    errors = sys.stderr if stderr is None else stderr
    try:
        config = os.environ if environ is None else environ
        manifest = validate_private_manual_runner(config)
        delivery = validate_encrypted_owner_delivery(config)
        if service_factory is None:
            from .auth import build_readonly_sheets_service_from_wif_adc
            service_factory = build_readonly_sheets_service_from_wif_adc
        service = service_factory()
        report = inspect_manual_approved_sheets(
            service, manifest=manifest,
            include_sensitive_records=delivery is not None)
        if delivery is not None:
            from .private_result_file import stage_owner_report
            stage_owner_report(report, **delivery)
    except Exception:
        errors.write('Private supplier read refused; review access and source configuration. No details emitted.\n')
        return 1
    output.write(json.dumps(
        report['public_summary'], sort_keys=True, separators=(',', ':')) + '\n')
    # NO persistence, file/artifact writing, or values in public log.
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 1:
        sys.stderr.write('This manual entrypoint does not accept command-line data.\n')
        raise SystemExit(2)
    raise SystemExit(main())
