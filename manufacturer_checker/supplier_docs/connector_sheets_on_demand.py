"""On-demand, PRIVATE Google Sheets-only supplier lookup.

Supports 1-5 explicitly selected Sheet tabs without requiring an Excel file.
The caller first uses its authenticated Google Drive connector to validate
file/tab access, retrieve visible metadata and read ONLY A1:O40 with FORMULA
rendering. This offline module accepts the already-authorized cell arrays.

No Google API, credentials, network, authorization checks, filesystem writes,
purchase action or unbounded folder discovery occur in this module.
Default return is anonymous; opt-in details are private and must never be
committed, logged, or shared across user sessions.
"""

from .connector_sheet_snapshot import normalize_selected_connector_snapshots
from .multi_source_readonly import validate_source_lookup
from .private_hit_review import (
    prepare_selected_private_hit_review, validate_private_reviewer_context,
)

SCHEMA_VERSION = 'manual-connector-sheets-on-demand-v1'


def _validate_search(search, required=False):
    if search is None:
        if required:
            raise ValueError('private search query is required')
        return
    if not isinstance(search, dict) or set(search) != {'field', 'query'}:
        raise ValueError('invalid on-demand search')
    validate_source_lookup(search['field'], search['query'])


def _normalize(manifest, search):
    result = normalize_selected_connector_snapshots(
        manifest=manifest, search=search)
    summary = result['public_summary']
    docs = result['private_normalized_docs']

    # Public summaries are constructed solely from the already privacy-safe
    # normalizer summary and numeric warning COUNTS, never from row text.
    warning_count = sum(
        'JAN_NUMERIC_CELL' in warning.get('codes', [])
        for doc in docs for warning in doc.get('warnings', [])
    )
    counts = dict(summary)
    counts.update({
        'schema_version': SCHEMA_VERSION,
        'source_kind': 'sheets',
        'numeric_jan_candidates_require_review': warning_count,
        'formula_cells_in_supplied_sheet_windows':
            summary['formula_cells_present'],
        'formula_cell_values_not_evaluated': True,
        'source_formula_fidelity_verified': False,
        'native_export_price_or_lot_trust_allowed': False,
        'upstream_connector_auth_verified_by_this_function': False,
        'upstream_connector_calls_performed_by_this_function': 0,
        'python_google_api_auth_verified': False,
        'all_supplier_folders_searched': False,
        'profit_calculation_allowed': False,
        'purchase_allowed': False,
        'source_writes': 0,
    })
    return result, counts


def inspect_selected_connector_sheets(*, connector_sheet_manifest, search=None):
    """Anonymous bounded summary of 1-5 selected native Google Sheets tabs."""
    _validate_search(search)
    normalized, summary = _normalize(connector_sheet_manifest, search)
    return {
        'status': 'manual_on_demand_connector_sheets_analyzed',
        'public_summary': summary,
        'public_search_summary': normalized.get('public_search_summary'),
        'private_details_returned': False,
    }


def inspect_selected_connector_sheets_for_review(
        *, connector_sheet_manifest, search, reviewer_context,
        source_labels=None, sheet_gid_by_url=None, max_hits=20):
    """PRIVATE hit details for an externally authorized user/session only.

    The four required caller assertions are NOT proof of Google access or
    user identity. The caller must independently check all selected files'
    permissions, visible tabs, trusted output destination and metadata gids.
    Never print/log/persist the return value or place it in GitHub or CI.
    """
    # Reject missing explicit private opt-in before reading any supplied rows.
    validate_private_reviewer_context(reviewer_context)
    _validate_search(search, required=True)
    normalized, _ = _normalize(connector_sheet_manifest, search)
    docs = normalized['private_normalized_docs']
    selected = {
        'private_normalized_docs': docs,
        'private_source_kinds': ['sheets'] * len(docs),
        'private_source_origins': [
            {
                'source_kind': 'sheets',
                'source_url': doc['source_url'],
                'source_sheet': doc['source_sheet'],
            }
            for doc in docs
        ],
        'public_search_summary': normalized['public_search_summary'],
        'private_hits': normalized['private_hits'],
    }
    return prepare_selected_private_hit_review(
        combined=selected, search=search, reviewer_context=reviewer_context,
        source_labels=source_labels, sheet_gid_by_url=sheet_gid_by_url,
        max_hits=max_hits,
    )
