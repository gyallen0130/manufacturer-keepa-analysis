"""Read-only, bounded on-demand paged Google Sheets supplier search.

An already authenticated caller selects 1..5 Google Sheets tabs, obtains
header rows A1:O<H> and *explicitly contiguous* FORMULA-rendered data windows,
and passes the cell matrices here privately. This module does NOT authenticate
users, call Google, save data, evaluate formulas or infer global completeness.

The original Google Sheets physical row numbers are restored after each page
is parsed. Normal public results contain only anonymous aggregate counts.
"""
from collections import Counter

from .connector_sheet_snapshot import (
    SCHEMA_VERSION as SNAPSHOT_VERSION, MODE as SNAPSHOT_MODE,
    normalize_selected_connector_snapshots,
)
from .drive_delta import FILE_ID
from .multi_source_readonly import search_selected_sources, validate_source_lookup
from .private_hit_review import (
    prepare_selected_private_hit_review, validate_private_reviewer_context,
)

SCHEMA_VERSION = 'manual-connector-sheet-pages-v1'
MODE = 'manual_paged_readonly'
MAX_TABS = 5
MAX_PAGES = 5
MAX_ROWS_PER_WINDOW = 40
MAX_COLS = 15
MAX_HEADER_ROWS = 20
MAX_TOTAL_DATA_ROWS = 200
_SOURCE_KEYS = frozenset((
    'spreadsheet_id', 'sheet_name', 'document_type',
    'snapshot_method', 'header_rows', 'header_row', 'pages',
))
_PAGE_KEYS = frozenset(('start_row', 'end_row', 'rows'))
_SOURCE_OPTIONAL_KEYS = frozenset(('data_start_row',))


def _text_cells(rows, *, limit):
    if (not isinstance(rows, list) or len(rows) > limit
            or any(not isinstance(row, list) or len(row) > MAX_COLS
                   for row in rows)):
        raise ValueError('invalid bounded private page rows')
    for row in rows:
        for cell in row:
            if ((cell is not None and type(cell) not in (str, int, float, bool))
                    or isinstance(cell, str) and len(cell) > 4000):
                raise ValueError('invalid private page cell')
    return rows


def _check_request(manifest, search):
    if (not isinstance(manifest, dict)
            or set(manifest) != {'schema_version', 'mode', 'sources'}
            or manifest['schema_version'] != SCHEMA_VERSION
            or manifest['mode'] != MODE
            or not isinstance(manifest['sources'], list)
            or not 1 <= len(manifest['sources']) <= MAX_TABS):
        raise ValueError('invalid explicit selected Sheets page manifest')
    if search is not None:
        if not isinstance(search, dict) or set(search) != {'field', 'query'}:
            raise ValueError('invalid page search')
        validate_source_lookup(search['field'], search['query'])

    keys_seen, page_count, row_total = set(), 0, 0
    checked = []
    for source in manifest['sources']:
        if (not isinstance(source, dict)
                or not _SOURCE_KEYS <= set(source)
                or not set(source) <= _SOURCE_KEYS | _SOURCE_OPTIONAL_KEYS):
            raise ValueError('invalid private paged source')
        fid = source['spreadsheet_id']
        tab = source['sheet_name']
        if (not isinstance(fid, str) or not FILE_ID.fullmatch(fid)
                or not isinstance(tab, str)
                or not tab.strip() or len(tab) > 100
                or any(ord(c) < 32 or c == '!' for c in tab)):
            raise ValueError('invalid selected Google source')
        key = (fid, tab)
        if key in keys_seen:
            raise ValueError('duplicate selected Google sheet tab')
        keys_seen.add(key)
        h = source['header_row']
        head = source['header_rows']
        if type(h) is not int or not 1 <= h <= MAX_HEADER_ROWS:
            raise ValueError('unverified explicit original header row')
        _text_cells(head, limit=MAX_HEADER_ROWS)
        if len(head) != h:
            raise ValueError('header_rows must contain every original row 1 through header_row')
        pages = source['pages']
        if not isinstance(pages, list) or not pages:
            raise ValueError('at least one explicit data range required')

        expected_row = source.get('data_start_row', h + 1)
        if (type(expected_row) is not int
                or not h + 1 <= expected_row <= 1000000):
            raise ValueError('invalid explicit original page starting row')
        validated = []
        for page in pages:
            if not isinstance(page, dict) or set(page) != _PAGE_KEYS:
                raise ValueError('invalid private page specification')
            start, end, data = page['start_row'], page['end_row'], page['rows']
            if (type(start) is not int or type(end) is not int
                    or start != expected_row or not start <= end
                    or end - start + 1 > MAX_ROWS_PER_WINDOW - h):
                raise ValueError('noncontiguous or oversized original row range')
            _text_cells(data, limit=end-start+1)
            # Values.get may omit trailing empty rows. Restore only blanks
            # within the caller-verified, explicitly requested rectangle.
            padded = data + [[] for _ in range(end - start + 1 - len(data))]
            validated.append((start, end, padded, len(data)))
            expected_row = end + 1
            page_count += 1
            row_total += end-start+1
        checked.append((source, validated))
    if page_count > MAX_PAGES or row_total > MAX_TOTAL_DATA_ROWS:
        raise ValueError('selected page budget exceeded')
    return checked, page_count, row_total


def _collect(*, manifest, search):
    checked, page_count, rows_requested = _check_request(manifest, search)
    docs, kinds, origins = [], [], []
    statuses = Counter()
    record_total, numeric_warnings, formulas, trailing_blank = 0, 0, 0, 0
    pages_parsed = 0
    for source, pages in checked:
        h = source['header_row']
        head = source['header_rows']
        formulas += sum(isinstance(v,str) and v.lstrip().startswith('=')
                        for row in head for v in row)
        merged_records, merged_warnings = [], []
        original_doc = None
        expected_status = None
        expected_mapping = None
        for start, end, data, actual_row_count in pages:
            trailing_blank += end-start+1-actual_row_count
            formulas += sum(isinstance(v,str) and v.lstrip().startswith('=')
                            for row in data for v in row)
            selected = {
                'schema_version': SNAPSHOT_VERSION,
                'mode': SNAPSHOT_MODE,
                'sources': [{
                    'spreadsheet_id': source['spreadsheet_id'],
                    'sheet_name': source['sheet_name'],
                    'document_type': source['document_type'],
                    'snapshot_method': source['snapshot_method'],
                    'header_row': h,
                    'rows': head + data,
                }],
            }
            result = normalize_selected_connector_snapshots(manifest=selected)
            doc = result['private_normalized_docs'][0]
            status = doc['source_status']
            # Unlabeled source profit commentary can be inferred on one
            # bounded page and absent on another. That field is neither
            # searched nor exposed by the private viewer: ignore only this
            # inference for cross-page stability. Identity-related fields,
            # including inferred ASIN, must agree on every page.
            search_inferences = {
                key: value for key, value in
                doc.get('inferred_columns', {}).items()
                if key != 'source_profit_label'
            }
            mappings = (doc.get('mapped_columns', {}), search_inferences)
            if original_doc is None:
                original_doc, expected_status, expected_mapping = doc, status, mappings
            elif status != expected_status or mappings != expected_mapping:
                # Do not silently combine pages with inconsistent header or
                # unlabeled ASIN evidence.
                raise ValueError('page header or inferred mapping changed')
            offset = start - h - 1
            for rec in doc['records']:
                row = rec['source_row'] + offset
                if type(row) is not int or not start <= row <= end:
                    raise ValueError('out-of-range original product row')
                copy = dict(rec)
                copy['source_row'] = row
                merged_records.append(copy)
            for warning in doc['warnings']:
                row = warning.get('row')
                if type(row) is not int or not 1 <= row <= h+len(data):
                    raise ValueError('out-of-range original warning row')
                # Header-level warnings repeat on every page. Keep once.
                if row <= h and original_doc is not doc:
                    continue
                warning_copy = dict(warning)
                if row > h:
                    warning_copy['row'] = row + offset
                merged_warnings.append(warning_copy)
            pages_parsed += 1
        doc = dict(original_doc)
        doc['records'] = merged_records
        doc['warnings'] = merged_warnings
        doc['summary'] = {
            'record_count': len(merged_records),
            'warning_count': len(merged_warnings),
        }
        docs.append(doc)
        kinds.append('sheets')
        origins.append({
            'source_kind': 'sheets',
            'source_url': doc['source_url'],
            'source_sheet': doc['source_sheet'],
        })
        record_total += len(merged_records)
        statuses[doc['source_status']] += 1
        numeric_warnings += sum(
            'JAN_NUMERIC_CELL' in w.get('codes', []) for w in merged_warnings)

    searchable = {'private_normalized_docs': docs}
    private = {
        **searchable,
        'private_source_kinds': kinds,
        'private_source_origins': origins,
    }
    search_summary = None
    if search is not None:
        matched = search_selected_sources(searchable, **search)
        private['private_hits'] = matched['private_hits']
        search_summary = matched['public_summary']
        private['public_search_summary'] = search_summary
    public = {
        'schema_version': SCHEMA_VERSION,
        'mode': MODE,
        'source_count': len(docs),
        'page_count': page_count,
        'pages_parsed': pages_parsed,
        'rows_requested_excluding_header': rows_requested,
        'trailing_rows_unpopulated_in_connector_response': trailing_blank,
        'record_count': record_total,
        'source_status_counts': {
            key: statuses[key] for key in
            ('parsed','mapped_review','labeled_review','needs_review','empty')
        },
        'numeric_jan_candidates_require_review': numeric_warnings,
        'formula_cells_in_supplied_sheet_windows': formulas,
        'formula_cell_values_not_evaluated': True,
        'all_selected_pages_parsed': pages_parsed == page_count,
        'all_supplier_folders_searched': False,
        'all_rows_in_selected_tabs_searched': False,
        'source_formula_fidelity_verified': False,
        'upstream_connector_auth_verified_by_this_function': False,
        'python_google_api_auth_verified': False,
        'profit_calculation_allowed': False,
        'purchase_allowed': False,
        'source_writes': 0,
        'api_calls': 0,
    }
    return private, public, search_summary


def inspect_selected_connector_sheet_pages(*, manifest, search=None):
    """Anonymous page counts and selected-range match counts only."""
    _, public, search_summary = _collect(manifest=manifest, search=search)
    return {
        'status': 'manual_paged_sheets_analyzed',
        'public_summary': public,
        'public_search_summary': search_summary,
        'private_details_returned': False,
    }


def inspect_selected_connector_sheet_pages_for_review(
        *, manifest, search, reviewer_context, source_labels=None,
        sheet_gid_by_url=None, max_hits=20):
    """PRIVATE only; caller must independently authenticate file/user access."""
    validate_private_reviewer_context(reviewer_context)
    if search is None:
        raise ValueError('private review requires a bounded search')
    selected, _, _ = _collect(manifest=manifest, search=search)
    return prepare_selected_private_hit_review(
        combined=selected, search=search, reviewer_context=reviewer_context,
        source_labels=source_labels, sheet_gid_by_url=sheet_gid_by_url,
        max_hits=max_hits,
    )
