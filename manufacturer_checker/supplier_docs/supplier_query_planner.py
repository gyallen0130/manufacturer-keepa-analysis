"""PRIVATE, read-only planning for ChatGPT-driven supplier Google Sheet searches.

The caller obtains metadata and checks file access with its independently
authenticated Drive connector BEFORE calling this module. The metadata flags
are declarations, not authentication proof. No networking, OAuth, row reads,
storage, writes, source discovery, billing or supplier inference occur here.

Only the explicitly selected supplier's verified visible tab metadata may be
planned. The returned plan contains supplier/file names and IDs: PRIVATE ONLY.
It must never be logged or committed to public GitHub. Actual product data is
also PRIVATE; the caller may publish only the existing anonymized parser
summaries, never this plan or its source rows.
"""
import unicodedata

from .connector_sheets_paged import (
    SCHEMA_VERSION as PAGE_SCHEMA, MODE as PAGE_MODE,
    MAX_PAGES, MAX_TABS, MAX_TOTAL_DATA_ROWS, MAX_ROWS_PER_WINDOW,
    _check_request, _text_cells,
)
from .drive_delta import FILE_ID
from .multi_source_readonly import DOCUMENT_TYPES

SCHEMA_VERSION = 'private-supplier-on-demand-plan-v1'
MAX_CATALOG_TABS = 160
_METADATA_FIELDS = frozenset((
    'supplier_label', 'spreadsheet_id', 'sheet_name', 'sheet_gid',
    'grid_rows', 'grid_columns', 'header_row', 'document_type',
    'visible', 'source_access_checked',
))
_RESPONSE_FIELDS = frozenset((
    'spreadsheet_id', 'sheet_name', 'requested_range', 'rows',
))


def _name(value, *, max_length=120):
    if (not isinstance(value, str) or not value.strip()
            or len(value) > max_length
            or any(ord(c) < 32 for c in value)):
        raise ValueError('invalid private supplier or Sheet name')
    return unicodedata.normalize('NFKC', value).strip().casefold()


def _validated_catalog(approved_tab_metadata):
    if (not isinstance(approved_tab_metadata, list)
            or not 1 <= len(approved_tab_metadata) <= MAX_CATALOG_TABS):
        raise ValueError('approved private catalog must be bounded')
    seen = set()
    for entry in approved_tab_metadata:
        if not isinstance(entry, dict) or set(entry) != _METADATA_FIELDS:
            raise ValueError('unexpected private Google tab metadata')
        label = _name(entry['supplier_label'])
        fid, tab = entry['spreadsheet_id'], entry['sheet_name']
        if (not isinstance(fid, str) or not FILE_ID.fullmatch(fid)
                or not isinstance(tab, str)
                or not 1 <= len(tab) <= 100 or '!' in tab
                or any(ord(c) < 32 for c in tab)):
            raise ValueError('invalid selected file ID or tab')
        gid, row_count, col_count, header = (
            entry['sheet_gid'], entry['grid_rows'],
            entry['grid_columns'], entry['header_row'])
        if (type(gid) is not int or not 0 <= gid <= 2147483647
                or type(row_count) is not int or not 2 <= row_count <= 1000000
                or type(col_count) is not int or not 15 <= col_count <= 1000
                or type(header) is not int or not 1 <= header <= 20
                or header >= row_count
                or entry['document_type'] not in DOCUMENT_TYPES
                or entry['visible'] is not True
                or entry['source_access_checked'] is not True):
            raise ValueError('selected tab is not a validated readable range')
        key = (fid, tab)
        if key in seen:
            raise ValueError('duplicate approved metadata for one tab')
        seen.add(key)
    return approved_tab_metadata


def plan_supplier_sheet_reads(*, supplier_query, approved_tab_metadata):
    """Select a unique supplier by name and budget at most 5 range pages.

    The input is a PRIVATE, externally approved Google tab metadata catalog,
    NOT a request to scan Drive. Match names exactly first; a unique
    substring match is allowed, but ambiguous matches are rejected.
    Every selected tab gets its first page. Remaining pages are assigned in
    round-robin order. Sheets gridRowCount is a CAPACITY, not evidence that
    every physical row has data, and not a freshness check.
    """
    query = _name(supplier_query, max_length=80)
    catalog = _validated_catalog(approved_tab_metadata)
    labels = {_name(x['supplier_label']) for x in catalog}
    chosen = {query} if query in labels else {
        label for label in labels if query in label
    }
    if len(chosen) != 1:
        raise ValueError('supplier not uniquely identified in approved catalog')
    matches = [entry for entry in catalog
               if _name(entry['supplier_label']) in chosen]
    if not 1 <= len(matches) <= MAX_TABS:
        raise ValueError('supplier has too many selected tabs; narrow the selection')

    # Preserve the trusted catalog order and do not manufacture other tabs.
    selected = []
    for entry in matches:
        header = entry['header_row']
        selected.append({
            'supplier_label': entry['supplier_label'],
            'spreadsheet_id': entry['spreadsheet_id'],
            'sheet_name': entry['sheet_name'],
            'sheet_gid': entry['sheet_gid'],
            'grid_rows': entry['grid_rows'],
            'document_type': entry['document_type'],
            'header_row': header,
            'header_range': f'A1:O{header}',
            'data_pages': [],
        })
    total_pages, total_rows = 0, 0
    # Important: do not starve the second tab by filling the first first.
    while total_pages < MAX_PAGES and total_rows < MAX_TOTAL_DATA_ROWS:
        progress = False
        for src in selected:
            if total_pages >= MAX_PAGES or total_rows >= MAX_TOTAL_DATA_ROWS:
                break
            start = (src['header_row'] + 1 if not src['data_pages']
                     else src['data_pages'][-1]['end_row'] + 1)
            if start > src['grid_rows']:
                continue
            remaining = MAX_TOTAL_DATA_ROWS - total_rows
            size = min(MAX_ROWS_PER_WINDOW - src['header_row'],
                       src['grid_rows'] - start + 1, remaining)
            if size < 1:
                continue
            end = start + size - 1
            src['data_pages'].append({
                'start_row': start, 'end_row': end,
                'requested_range': f'A{start}:O{end}',
            })
            total_pages += 1
            total_rows += size
            progress = True
        if not progress:
            break

    if any(not src['data_pages'] for src in selected):
        raise ValueError('no page budget for selected supplier tab')
    return {
        'schema_version': SCHEMA_VERSION,
        'privacy_classification': 'PRIVATE_SOURCE_SELECTION_NEVER_LOG',
        'supplier_name_inferred_from_file_title': False,
        'source_access_verified_by_this_function': False,
        'read_only': True,
        'connector_calls_performed': 0,
        'selected_supplier_label': matches[0]['supplier_label'],
        'selected_tabs': len(selected),
        'planned_pages': total_pages,
        'planned_data_rows': total_rows,
        'selected_sources': selected,
        'unread_grid_rows_remain': any(
            src['data_pages'][-1]['end_row'] < src['grid_rows']
            for src in selected),
        'all_supplier_folders_searched': False,
        'all_product_rows_verified': False,
    }


def build_private_page_manifest(*, plan, connector_responses):
    """Bind externally fetched FORMULA responses to EXACT planned ranges.

    Reject missing, duplicate, extra or swapped file/tab/range responses.
    This validates caller-supplied responses but CANNOT prove connector
    authentication, the actual rendering option, or external API freshness.
    Callers MUST request FORMULA and fail on network/API errors themselves.
    """
    if (not isinstance(plan, dict) or
            plan.get('schema_version') != SCHEMA_VERSION or
            plan.get('privacy_classification')
            != 'PRIVATE_SOURCE_SELECTION_NEVER_LOG'):
        raise ValueError('invalid private read plan')
    sources = plan.get('selected_sources')
    if (not isinstance(sources, list)
            or not 1 <= len(sources) <= MAX_TABS):
        raise ValueError('invalid selected private sources')
    if not isinstance(connector_responses, list):
        raise ValueError('private connector responses must be ordered list')

    needed = {}
    for src in sources:
        if not isinstance(src, dict):
            raise ValueError('invalid private source plan')
        fid, tab = src.get('spreadsheet_id'), src.get('sheet_name')
        if (not isinstance(fid, str) or not FILE_ID.fullmatch(fid)
                or not isinstance(tab, str) or not tab):
            raise ValueError('invalid source plan identity')
        requests = [src.get('header_range')] + [
            x['requested_range'] for x in src.get('data_pages', [])]
        for rng in requests:
            if not isinstance(rng, str):
                raise ValueError('invalid planned range')
            key = (fid, tab, rng)
            if key in needed:
                raise ValueError('repeated private planned range')
            needed[key] = None

    if len(connector_responses) != len(needed):
        raise ValueError('missing or extra private connector responses')
    for item in connector_responses:
        if not isinstance(item, dict) or set(item) != _RESPONSE_FIELDS:
            raise ValueError('unrecognized connector response')
        key = (item['spreadsheet_id'], item['sheet_name'],
               item['requested_range'])
        if key not in needed or needed[key] is not None:
            raise ValueError('unexpected, duplicate or wrong-source range')
        rows = item['rows']
        # Limit is later confirmed against the exact original rectangle.
        _text_cells(rows, limit=MAX_ROWS_PER_WINDOW)
        needed[key] = rows

    manifests = []
    for src in sources:
        fid, tab = src['spreadsheet_id'], src['sheet_name']
        h = src['header_row']
        header = needed[(fid, tab, src['header_range'])]
        if len(header) != h:
            raise ValueError('incomplete private header response')
        pages = []
        for page in src['data_pages']:
            key = (fid, tab, page['requested_range'])
            rows = needed[key]
            if len(rows) > page['end_row'] - page['start_row'] + 1:
                raise ValueError('extra rows beyond requested page')
            pages.append({
                'start_row': page['start_row'],
                'end_row': page['end_row'],
                'rows': rows,
            })
        manifests.append({
            'spreadsheet_id': fid,
            'sheet_name': tab,
            'document_type': src['document_type'],
            'snapshot_method': 'connector_formula_values',
            'header_row': h,
            'header_rows': header,
            'pages': pages,
        })
    paged = {
        'schema_version': PAGE_SCHEMA,
        'mode': PAGE_MODE,
        'sources': manifests,
    }
    # Reject inconsistent caller-forged page definitions BEFORE parsing.
    _check_request(paged, search=None)
    return paged


def summarize_plan_without_private_sources(plan):
    """Only safe, anonymous progress/coverage stats; never row details."""
    if (not isinstance(plan, dict)
            or plan.get('schema_version') != SCHEMA_VERSION
            or plan.get('privacy_classification')
            != 'PRIVATE_SOURCE_SELECTION_NEVER_LOG'):
        raise ValueError('invalid private plan')
    sources = plan.get('selected_sources')
    if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_TABS:
        raise ValueError('invalid private plan sources')
    return {
        'selected_source_tabs': len(sources),
        'planned_page_reads': sum(len(x['data_pages']) for x in sources),
        'planned_header_reads': len(sources),
        'planned_data_rows': sum(
            p['end_row'] - p['start_row'] + 1
            for x in sources for p in x['data_pages']),
        'unread_grid_rows_remain': bool(plan.get('unread_grid_rows_remain')),
        'all_supplier_folders_searched': False,
        'all_product_rows_verified': False,
        'source_access_verified_by_this_function': False,
        'connector_calls_performed': 0,
    }
