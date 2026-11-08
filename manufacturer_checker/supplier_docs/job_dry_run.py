"""Cloud Run Job-compatible OFFLINE dry-run entrypoint (synthetic data only).

Example: python -m supplier_docs.job_dry_run --scenario after_scan

No credentials, Google Cloud client, Secrets, real folder names, real file
IDs, production environment, or automatic receipt issuance is used here.
The hardcoded signing key is fake test data and MUST NEVER be used for review.
"""
import argparse
from datetime import datetime, timezone
import json

from .drive_delta import SCHEMA_VERSION
from .recovery import assess_recovery
from .review_gate import issue_review_receipt

_SYNTHETIC_KEY = b'fake-only-not-a-production-signing-key!'
_F = 'fake_folder_supplier123'
_CHANGED = 'fake_sheet_changed123'
_NEW = 'fake_sheet_added123'
_LOST = 'fake_sheet_unavailable123'
_MIME = 'application/vnd.google-apps.spreadsheet'
_FAKE_REVIEWER = 'fake_reviewer_01'
_FAKE_EVIDENCE = 'fake_evidence_0001'
_WHEN = datetime(2026, 1, 1, tzinfo=timezone.utc)

SCENARIOS = (
    'after_scan', 'partial_review', 'all_reviewed',
    'cas_committed', 'cas_conflict', 'unchanged',
)


def _fixture(files):
    return {_F: {
        'schema_version': SCHEMA_VERSION, 'folder_id': _F,
        'files': {doc: {'mime_type': _MIME, 'version': version,
                         'modified_time': ''}
                  for doc, version in files.items()},
        'total_items': len(files), 'pages_scanned': 1,
        'unsupported_items': 0, 'unscanned_subfolders': 0,
    }}


def simulate(scenario):
    """Return a redacted assessment for one of six fully synthetic crashes."""
    if scenario not in SCENARIOS:
        raise ValueError('unknown dry-run scenario')
    old = _fixture({_CHANGED: '1', _LOST: '1'})
    new = _fixture({_CHANGED: '2', _NEW: '1'})
    receipts = []
    selected = ([])
    if scenario == 'partial_review':
        selected = [(_CHANGED, 'changed')]
    elif scenario in ('all_reviewed', 'cas_committed'):
        selected = [(_CHANGED, 'changed'), (_NEW, 'changed'),
                    (_LOST, 'unavailable')]
    if scenario == 'unchanged':
        new = old
    for file_id, event in selected:
        # Test-only signing against invented values, never real documents.
        receipts.append(issue_review_receipt(
            old, new, folder_id=_F, file_id=file_id, event=event,
            reviewer_id=_FAKE_REVIEWER, evidence_ref=_FAKE_EVIDENCE,
            reviewed_at=_WHEN, signing_key=_SYNTHETIC_KEY))
    persisted = new if scenario == 'cas_committed' else old
    generation = 3 if scenario == 'cas_conflict' else (
        2 if scenario == 'cas_committed' else 1)
    result = assess_recovery(
        old, new, persisted, receipts=receipts,
        signing_key=_SYNTHETIC_KEY, allowed_reviewers={_FAKE_REVIEWER},
        expected_generation=1, observed_generation=generation)
    return {
        'mode': 'synthetic_offline_dry_run',
        'scenario': scenario,
        **result,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Synthetic dry run only: never connects to Google Cloud.')
    parser.add_argument('--scenario', choices=SCENARIOS, default='after_scan')
    args = parser.parse_args(argv)
    print(json.dumps(simulate(args.scenario),
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
