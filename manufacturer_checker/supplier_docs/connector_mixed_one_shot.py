"""Manual, privacy-preserving Excel + authenticated-connector Sheet snapshot probe.

The caller obtains explicitly selected Sheet cell matrices via an already
authorized connector OUTSIDE this module, then passes them in memory. No
tokens, Google API calls, file discovery, writes or network occur here.
The caller must not print or persist the supplied snapshots or any private
rows. Only the aggregate dictionaries returned here are shareable.
"""
from .connector_sheet_snapshot import (
    normalize_selected_connector_snapshots, SCHEMA_VERSION as SNAPSHOT_VERSION,
    MODE as SNAPSHOT_MODE,
)
from .local_excel_bridge import (
    inspect_selected_local_excel, validate_excel_manifest,
)
from .mixed_source_readonly import combine_selected_source_results
from .multi_source_readonly import MAX_SOURCES, validate_source_lookup


def _collect_private_sources(*, root_dir, excel_manifest,
                             connector_sheet_manifest, search):
    """Shared bounded selection and parsing, without authentication or writes."""
    selected_excel = validate_excel_manifest(excel_manifest)
    if (not isinstance(connector_sheet_manifest, dict)
            or set(connector_sheet_manifest) != {
                'schema_version', 'mode', 'sources'
            }
            or connector_sheet_manifest['schema_version'] != SNAPSHOT_VERSION
            or connector_sheet_manifest['mode'] != SNAPSHOT_MODE
            or not isinstance(connector_sheet_manifest['sources'], list)):
        raise ValueError('invalid private connector source manifest')

    source_count = len(connector_sheet_manifest['sources'])
    if (not 1 <= source_count <= MAX_SOURCES
            or len(selected_excel) + source_count > MAX_SOURCES):
        raise ValueError('five combined source tabs maximum')
    if search is not None:
        if not isinstance(search, dict) or set(search) != {'field', 'query'}:
            raise ValueError('invalid private lookup')
        validate_source_lookup(search['field'], search['query'])

    # Both source types are validated before any workbook content is read.
    sheets = normalize_selected_connector_snapshots(
        manifest=connector_sheet_manifest)
    excel = inspect_selected_local_excel(
        root_dir=root_dir, manifest=excel_manifest)
    combined = combine_selected_source_results(
        [excel, sheets], search=search)

    return combined, sheets


def inspect_private_connector_mixed(*, root_dir, excel_manifest,
                                    connector_sheet_manifest, search=None):
    """Combine authorized in-memory Sheet windows and local Excel (<=5 tabs).

    No auth is acquired or verified. Use an independently authorized connector
    for the Sheet windows, A1:O40 maximum, and keep the raw arrays private.

    The function returns public summaries ONLY; downstream source rows and
    detailed hits are discarded. A zero local API count never means the caller
    did not perform an upstream connector read.
    """
    combined, sheets = _collect_private_sources(
        root_dir=root_dir,
        excel_manifest=excel_manifest,
        connector_sheet_manifest=connector_sheet_manifest,
        search=search,
    )

    aggregate = dict(combined['public_summary'])
    # The parser can preserve numeric JANs as SEARCH CANDIDATES with a warning.
    # A numeric cell may have lost a leading zero; never treat the identifier
    # as a verified product identity. Only publish the warning COUNT.
    numeric_jan_warnings = sum(
        'JAN_NUMERIC_CELL' in warning.get('codes', [])
        for doc in combined['private_normalized_docs']
        for warning in doc.get('warnings', [])
    )
    # Exported native Sheets can differ from live FORMULA values. A claimed
    # native export is NEVER evidence of complete formula fidelity or a
    # trustworthy supplier price/lot, even if parsing succeeded.
    exported_sheet_count = sum(
        source['snapshot_method'] == 'native_export_xlsx'
        for source in connector_sheet_manifest['sources']
    )
    aggregate.update({
        'formula_cells_in_supplied_sheet_windows': sheets['public_summary']['formula_cells_present'],
        'formula_cell_values_not_evaluated': True,
        'numeric_jan_candidates_require_review': numeric_jan_warnings,
        'native_sheet_exports_require_formula_review': exported_sheet_count,
        'native_export_price_or_lot_trust_allowed': False,
        'source_formula_fidelity_verified': False,
        'upstream_connector_cells_read_by_this_function': 0,
        'upstream_connector_auth_verified_by_this_function': False,
        'python_google_api_auth_verified': False,
        'sheet_windows_supplied_in_memory': source_count,
        'profit_calculation_allowed': False,
        'purchase_allowed': False,
        'source_writes': 0,
    })
    return {
        'status': 'manual_connector_snapshot_plus_excel_analyzed',
        'public_summary': aggregate,
        'public_search_summary': combined.get('public_search_summary'),
        'private_details_returned': False,
    }



def inspect_private_connector_mixed_for_review(
        *, root_dir, excel_manifest, connector_sheet_manifest,
        search, reviewer_context, source_labels=None, max_hits=20):
    """Return a PRIVATE, user-visible selected-source hit review.

    The calling application MUST enforce identity, selected-file access and
    private destination. The caller's four affirmative context flags are
    declarations, NOT authentication. This function has no access to Google
    OAuth, user accounts, network, public CI or persistent storage.

    The public-only inspect_private_connector_mixed() remains the default.
    NEVER print/log/commit this function's return value.
    """
    from .private_hit_review import (
        prepare_selected_private_hit_review,
        validate_private_reviewer_context,
    )
    # Fail early: a missing explicit opt-in must not even open private files.
    validate_private_reviewer_context(reviewer_context)
    if search is None:
        raise ValueError('private review requires a search')
    combined, _ = _collect_private_sources(
        root_dir=root_dir,
        excel_manifest=excel_manifest,
        connector_sheet_manifest=connector_sheet_manifest,
        search=search,
    )
    return prepare_selected_private_hit_review(
        combined=combined, search=search,
        reviewer_context=reviewer_context,
        source_labels=source_labels, max_hits=max_hits,
    )
