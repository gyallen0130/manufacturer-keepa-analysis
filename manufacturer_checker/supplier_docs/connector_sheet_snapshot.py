"""Bounded private Google Sheets connector snapshot -> shared supplier search.

For environments with an already-authorized Google Drive connector where
transferring the connector's OAuth credentials to a Python process is neither
possible nor desirable. Caller supplies just the preselected cell matrix:
no authentication, remote calls, document discovery or file writes occur.

Results contain PRIVATE product rows, JANs, ASINs, filenames and origins.
Only public_summary / public_search_summary may be logged or shared.
"""
import re

from .drive_delta import FILE_ID
from .multi_source_readonly import (
    MAX_SOURCES, normalize_selected_sources, search_selected_sources,
    validate_source_lookup,
)
from .parser import DOCUMENT_TYPES
from .row_labeled_candidates import validate_row_label_mapping
from .tiered_header_mapping import validate_tiered_mapping_schema

SCHEMA_VERSION = 'manual-connector-sheet-snapshot-v1'
MODE = 'manual_snapshot_readonly'
MAX_ROWS = 40
MAX_COLS = 15
MAX_TEXT = 4000
_TAB = re.compile(r"^[^!\r\n\x00-\x1f]{1,100}$")
_METHODS = frozenset(('connector_formula_values', 'native_export_xlsx'))
_TARGET_KEYS = frozenset((
    'spreadsheet_id', 'sheet_name', 'document_type', 'rows',
    'snapshot_method', 'header_row', 'tiered_mapping',
    'row_labeled_mapping',
))


def normalize_selected_connector_snapshots(*, manifest, search=None):
    """Normalize 1-5 privately obtained, already-authorized Sheet windows.

    The external connector must confirm visibility/permissions and provide
    A1:O40 or smaller. This function cannot verify caller authentication.
    For native XLSX exports, workbook-to-cell conversion must happen in the
    same PRIVATE runtime; formula/type fidelity can differ from Sheets API.
    """
    if (not isinstance(manifest, dict)
            or set(manifest) != {'schema_version', 'mode', 'sources'}
            or manifest.get('schema_version') != SCHEMA_VERSION
            or manifest.get('mode') != MODE
            or not isinstance(manifest.get('sources'), list)
            or not 1 <= len(manifest['sources']) <= MAX_SOURCES):
        raise ValueError('invalid authorized Sheets snapshot manifest')
    if search is not None:
        if not isinstance(search, dict) or set(search) != {'field', 'query'}:
            raise ValueError('invalid private Sheets snapshot search')
        validate_source_lookup(search['field'], search['query'])

    selected, seen, methods, formulas = [], set(), {}, 0
    for entry in manifest['sources']:
        if (not isinstance(entry, dict)
                or not {'spreadsheet_id', 'sheet_name', 'document_type',
                        'rows', 'snapshot_method'} <= set(entry)
                or not set(entry) <= _TARGET_KEYS):
            raise ValueError('invalid selected Sheet snapshot')
        file_id, tab = entry['spreadsheet_id'], entry['sheet_name']
        kind, rows = entry['document_type'], entry['rows']
        method, header = entry['snapshot_method'], entry.get('header_row')
        tiered, labeled = entry.get('tiered_mapping'), entry.get('row_labeled_mapping')
        if (not isinstance(file_id, str) or not FILE_ID.fullmatch(file_id)
                or not isinstance(tab, str) or not _TAB.fullmatch(tab)
                or not tab.strip()
                or not isinstance(kind, str) or kind not in DOCUMENT_TYPES
                or not isinstance(method, str) or method not in _METHODS
                or (header is not None and (type(header) is not int
                                            or not 1 <= header <= 20))
                or not isinstance(rows, list) or len(rows) > MAX_ROWS
                or any(not isinstance(row, list) or len(row) > MAX_COLS
                       for row in rows)):
            raise ValueError('invalid Sheet source/window selection')
        if (tiered is not None) + (labeled is not None) + (header is not None) > 1:
            raise ValueError('conflicting manual mappings')
        if tiered is not None:
            validate_tiered_mapping_schema(tiered)
        if labeled is not None:
            validate_row_label_mapping(labeled)
        key = (file_id, tab)
        if key in seen:
            raise ValueError('duplicate selected Sheets source')
        seen.add(key)
        for row in rows:
            for cell in row:
                if (cell is not None and type(cell) not in (str, int, float, bool)
                        or isinstance(cell, str) and len(cell) > MAX_TEXT):
                    raise ValueError('untrusted compound or oversized Sheet cell')
                if isinstance(cell, str) and cell.lstrip().startswith('='):
                    formulas += 1
        methods[method] = methods.get(method, 0) + 1
        selected.append({
            'source_file_id': file_id,
            'source_sheet': tab,
            'source_url': f'https://docs.google.com/spreadsheets/d/{file_id}/edit',
            'document_type': kind,
            'header_row': header,
            'tiered_mapping': tiered,
            'row_labeled_mapping': labeled,
            'rows': rows,
        })

    parsed = normalize_selected_sources(selected)
    suppressed = 0
    # Exported XLSX may lose live Sheets formula/value-render semantics.
    # Preserve source column evidence, but suppress ANY quote/cost/lot
    # inference from native export rows. Product identities remain candidates.
    for doc, original in zip(parsed['private_normalized_docs'],
                             manifest['sources']):
        if original['snapshot_method'] != 'native_export_xlsx':
            continue
        doc['native_export_terms_require_review'] = True
        for record in doc['records']:
            suppressed += int(bool(record.get('cost_present')))
            record['cost_present'] = False
            record['cost_tax_mode'] = 'unknown'
            record['order_multiple'] = ''
            record['trade_terms_present'] = False
            record['source_profit_status'] = 'unclassified'
            record['decision'] = 'needs_confirmation'
    summary = dict(parsed['public_summary'])
    summary['records_with_cost_field'] = sum(
        bool(r.get('cost_present'))
        for doc in parsed['private_normalized_docs'] for r in doc['records'])
    summary['records_cost_tax_unknown'] = sum(
        bool(r.get('cost_present')) and r.get('cost_tax_mode') == 'unknown'
        for doc in parsed['private_normalized_docs'] for r in doc['records'])
    summary['native_export_cost_flags_suppressed'] = suppressed
    summary.update({
        'schema_version': SCHEMA_VERSION,
        'mode': MODE,
        'snapshot_source_counts': dict(sorted(methods.items())),
        'formula_cells_present': formulas,
        'connector_auth_verified_by_this_function': False,
        'connector_reads_performed_by_this_function': 0,
        'api_calls': 0,
        'source_writes': 0,
        'xlsx_export_type_fidelity_requires_review': bool(
            methods.get('native_export_xlsx')),
        'review_required': True,
    })
    result = {
        'public_summary': summary,
        'private_normalized_docs': parsed['private_normalized_docs'],
    }
    if search is not None:
        hit = search_selected_sources(parsed, **search)
        result['public_search_summary'] = hit['public_summary']
        result['private_hits'] = hit['private_hits']
    return result
