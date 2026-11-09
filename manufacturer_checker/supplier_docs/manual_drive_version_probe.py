"""Owner-invoked, metadata-only Google Drive v3 version probe.

Run only in a reviewed PRIVATE local/WIF environment with access to exactly
one approved source. Prints a boolean status only; never prints filenames,
file IDs, revision numbers, raw API responses, or OAuth error messages.

Does not create a workflow, enable APIs, modify IAM, or read Sheet cells.
"""
import argparse
import json
import os

from .auth import build_readonly_drive_metadata_service_from_wif_adc
from .drive_delta import FILE_ID
from .supplier_drive_version import make_googleapiclient_drive_version_reader


def run_version_probe(*, confirmed, file_id, service_factory=None):
    """Boolean-only receipt. Never return an actual source ID or version."""
    if confirmed is not True:
        raise ValueError('explicit metadata-only approval required')
    if not isinstance(file_id, str) or not FILE_ID.fullmatch(file_id):
        raise ValueError('exact approved Google Sheets file id required')
    factory = (build_readonly_drive_metadata_service_from_wif_adc
               if service_factory is None else service_factory)
    if not callable(factory):
        raise ValueError('restricted Drive metadata client factory required')
    # The PRIVATE caller is responsible for reviewing the WIF Reader and
    # source access before running. A Boolean CLI argument isn't IAM proof.
    reader = make_googleapiclient_drive_version_reader(factory())
    evidence = reader(spreadsheet_id=file_id)
    if not evidence.get('version'):
        raise ValueError('Google file version unavailable')
    return {
        'probe_schema': 'manual-drive-version-metadata-only-v1',
        'status': 'raw_drive_v3_monotonic_version_available',
        'read_only': True,
        'sheet_cells_read': False,
        'credentials_logged': False,
        'file_ids_logged': False,
        'version_values_logged': False,
        'wif_provider_verified_by_probe': False,
        'source_permissions_verified_by_probe': False,
        'no_persistent_state_written': True,
    }


def main(argv=None, *, environ=None, service_factory=None, output=None):
    parser = argparse.ArgumentParser(
        description='Manually verify raw Google Drive v3 version availability')
    parser.add_argument('--confirm-readonly', action='store_true')
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ
    write = print if output is None else output
    try:
        receipt = run_version_probe(
            confirmed=args.confirm_readonly,
            file_id=env.get('SUPPLIER_APPROVED_SHEET_ID'),
            service_factory=service_factory,
        )
    except Exception:
        # Do not put exception details in stdout/stderr. Google SDK errors
        # may contain full resource paths, sensitive headers, or user info.
        write(json.dumps({
            'probe_schema': 'manual-drive-version-metadata-only-v1',
            'status': 'blocked_version_or_auth_unavailable',
            'no_source_rows_read_by_probe': True,
        },sort_keys=True))
        return 1
    write(json.dumps(receipt,sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
