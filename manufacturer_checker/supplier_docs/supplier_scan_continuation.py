"""PRIVATE bounded continuation for long manufacturer Google Sheets.

One explicitly approved, visible Google Sheet tab is scanned in batches of at
most five 40-cell windows. Caller must independently authenticate the user,
validate Drive permissions, supply fresh metadata, and bind callbacks to the
authenticated FORMULA reader and source revision provider. This module makes
no Google/network/auth calls, stores no data and never writes to sources.

A PRIVATE cursor is an integrity/coverage aid, NOT an authorization token.
A revision must change whenever source content changes; if the host cannot
supply such a reliable marker, it MUST NOT enable cross-request continuation.
The header and last-row sentinels add checks but cannot detect edits to any
arbitrary earlier row without reliable provider revision semantics.
"""
import hashlib
import json

from .connector_sheets_paged import (
    SCHEMA_VERSION as PAGES_SCHEMA, MODE as PAGES_MODE,
    MAX_PAGES, MAX_ROWS_PER_WINDOW, inspect_selected_connector_sheet_pages,
    inspect_selected_connector_sheet_pages_for_review, _check_request,
    _text_cells,
)
from .multi_source_readonly import validate_source_lookup
from .private_hit_review import validate_private_reviewer_context
from .supplier_query_planner import plan_supplier_sheet_reads
from .supplier_drive_version import strict_revision_evidence

SCHEMA_VERSION = 'private-supplier-scan-cursor-v1'
CURSOR_KEYS = frozenset((
    'schema_version', 'source_fingerprint', 'query_fingerprint',
    'source_revision_fingerprint', 'header_fingerprint',
    'last_row_fingerprint', 'next_row', 'scanned_data_rows',
    'returned_hits_lower_bound', 'any_hit_truncation', 'complete',
))
_ENVELOPE_KEYS = frozenset((
    'spreadsheet_id', 'sheet_name', 'requested_range',
    'value_render_option', 'rows',
))


def _digest(value):
    try:
        packed = json.dumps(value, ensure_ascii=False, sort_keys=True,
                            allow_nan=False, separators=(',', ':')).encode()
    except (ValueError, TypeError, OverflowError):
        raise ValueError('noncanonical private source evidence') from None
    return hashlib.sha256(packed).hexdigest()


def _grid_row(rows):
    if not rows:
        return [None] * 15
    if len(rows) != 1:
        raise ValueError('unexpected boundary row response')
    return rows[0] + [None] * (15-len(rows[0]))


def _read(fetch_formula_range, source, requested_range, maximum_rows):
    kwargs = {
        'spreadsheet_id': source['spreadsheet_id'],
        'sheet_name': source['sheet_name'],
        'requested_range': requested_range,
        'value_render_option': 'FORMULA',
    }
    try:
        reply = fetch_formula_range(**kwargs)
    except Exception:
        raise RuntimeError('authorized Sheet range read failed') from None
    if (not isinstance(reply, dict)
            or set(reply) != _ENVELOPE_KEYS
            or any(reply[k] != kwargs[k] for k in kwargs)):
        raise ValueError('wrong-source, wrong-range or wrong-rendering response')
    rows = reply['rows']
    _text_cells(rows, limit=maximum_rows)
    return rows


def _revision(get_source_revision, source):
    try:
        info = get_source_revision(spreadsheet_id=source['spreadsheet_id'])
    except Exception:
        raise RuntimeError('authorized source revision read failed') from None
    version = strict_revision_evidence(
        evidence=info, expected_file_id=source['spreadsheet_id'])
    # Only a typed, strictly validated monotonic Drive v3 file version can
    # prove that previously examined batches were not modified. A timestamp
    # or revisions.list id is not an acceptable production fallback.
    return _digest(('google_drive_v3_monotonic_file_version', version))


def _check_cursor(cursor, *, source_digest, query_digest, header):
    if not isinstance(cursor, dict) or set(cursor) != CURSOR_KEYS:
        raise ValueError('invalid private scan cursor')
    if cursor['schema_version'] != SCHEMA_VERSION:
        raise ValueError('unsupported scan cursor schema')
    for key in ('source_fingerprint', 'query_fingerprint',
                'source_revision_fingerprint', 'header_fingerprint',
                'last_row_fingerprint'):
        value = cursor[key]
        if (not isinstance(value, str) or len(value) != 64
                or any(ch not in '0123456789abcdef' for ch in value)):
            raise ValueError('invalid scan cursor fingerprint')
    if (cursor['source_fingerprint'] != source_digest
            or cursor['query_fingerprint'] != query_digest):
        raise ValueError('source or search changed; restart scan')
    if (type(cursor['scanned_data_rows']) is not int
            or not 1 <= cursor['scanned_data_rows'] <= 1000000
            or type(cursor['next_row']) is not int
            or cursor['next_row'] != header+1+cursor['scanned_data_rows']
            or type(cursor['returned_hits_lower_bound']) is not int
            or cursor['returned_hits_lower_bound'] < 0
            or cursor['returned_hits_lower_bound'] > cursor['scanned_data_rows']
            or type(cursor['any_hit_truncation']) is not bool
            or type(cursor['complete']) is not bool
            or cursor['complete']):
        raise ValueError('invalid or already finished scan cursor')


def scan_next_selected_supplier_sheet(
        *, supplier_query, search, approved_tab_metadata,
        fetch_formula_range, get_source_revision, private_cursor=None,
        include_private_hits=False, reviewer_context=None, max_hits=20):
    """Scan next bounded batch; entire response and cursor are PRIVATE.

    Caller MUST check identity/Drive permissions independently on each call.
    When continuation is resumed, revision must be unchanged from the prior
    batch. Before/after revision checks also protect an individual batch.
    The cursor stays in private storage/session; never place in public GitHub.
    """
    if (not isinstance(search, dict) or set(search) != {'field', 'query'}):
        raise ValueError('bounded supplier search required')
    validate_source_lookup(search['field'], search['query'])
    if type(include_private_hits) is not bool:
        raise ValueError('invalid private display selector')
    if include_private_hits:
        validate_private_reviewer_context(reviewer_context)
        if type(max_hits) is not int or not 1 <= max_hits <= 20:
            raise ValueError('invalid private hit display bound')
    elif reviewer_context is not None:
        raise ValueError('private context without explicit opt-in')
    if not callable(fetch_formula_range) or not callable(get_source_revision):
        raise ValueError('authenticated read and revision adapters required')

    selection = plan_supplier_sheet_reads(
        supplier_query=supplier_query, approved_tab_metadata=approved_tab_metadata)
    if selection['selected_tabs'] != 1:
        raise ValueError('long scan continuation needs one selected tab')
    source = selection['selected_sources'][0]
    # The metadata and user query are a PRIVATE binding, not an auth token.
    source_digest = _digest({
        k: source[k] for k in (
            'supplier_label','spreadsheet_id','sheet_name','sheet_gid',
            'grid_rows','document_type','header_row')
    })
    query_digest = _digest(search)
    header = source['header_row']
    if private_cursor is not None:
        _check_cursor(private_cursor, source_digest=source_digest,
                      query_digest=query_digest, header=header)

    start = header + 1 if private_cursor is None else private_cursor['next_row']
    if start > source['grid_rows']:
        raise ValueError('no source grid rows left to scan')
    ranges = []
    row = start
    while row <= source['grid_rows'] and len(ranges) < MAX_PAGES:
        end = min(source['grid_rows'],
                  row+MAX_ROWS_PER_WINDOW-header-1)
        ranges.append((row, end))
        row = end+1

    revision_before = _revision(get_source_revision, source)
    if (private_cursor is not None and
            revision_before != private_cursor['source_revision_fingerprint']):
        raise ValueError('source revision changed; restart from beginning')
    head = _read(fetch_formula_range, source,
                 source['header_range'], header)
    if len(head) != header:
        raise ValueError('incomplete source header')
    header_digest = _digest(head)
    if (private_cursor is not None
            and header_digest != private_cursor['header_fingerprint']):
        raise ValueError('source header changed; restart scan')

    if private_cursor is not None:
        previous_row = start-1
        prior = _read(fetch_formula_range, source,
                      f'A{previous_row}:O{previous_row}', 1)
        if (_digest(_grid_row(prior))
                != private_cursor['last_row_fingerprint']):
            raise ValueError('source boundary row changed; restart scan')

    pages, last_row_hash = [], None
    for first, last in ranges:
        data = _read(fetch_formula_range, source,
                     f'A{first}:O{last}', last-first+1)
        pages.append({'start_row': first, 'end_row': last, 'rows': data})
        # The final row may be empty / omitted by the connector.
        if data and len(data) == last-first+1:
            last_row = [data[-1]]
        else:
            last_row = []
        last_row_hash = _digest(_grid_row(last_row))
    revision_after = _revision(get_source_revision, source)
    if revision_after != revision_before:
        raise ValueError('source changed during scan; discard entire batch')

    one_source = {
        'spreadsheet_id': source['spreadsheet_id'],
        'sheet_name': source['sheet_name'],
        'document_type': source['document_type'],
        'snapshot_method': 'connector_formula_values',
        'header_row': header,
        'header_rows': head,
        'data_start_row': start,
        'pages': pages,
    }
    manifest = {
        'schema_version': PAGES_SCHEMA,
        'mode': PAGES_MODE,
        'sources': [one_source],
    }
    _check_request(manifest, search)
    anonymous = inspect_selected_connector_sheet_pages(
        manifest=manifest, search=search)
    matched = anonymous['public_search_summary']
    batch_count = sum(end-first+1 for first, end in ranges)
    total_scanned = (0 if private_cursor is None else
                     private_cursor['scanned_data_rows']) + batch_count
    lower_bound = (0 if private_cursor is None else
                   private_cursor['returned_hits_lower_bound']) + matched['hits_returned']
    truncated = ((False if private_cursor is None else
                  private_cursor['any_hit_truncation'])
                 or matched['results_truncated'])
    complete = row > source['grid_rows']
    cursor = {
        'schema_version': SCHEMA_VERSION,
        'source_fingerprint': source_digest,
        'query_fingerprint': query_digest,
        'source_revision_fingerprint': revision_after,
        'header_fingerprint': header_digest,
        'last_row_fingerprint': last_row_hash,
        'next_row': row,
        'scanned_data_rows': total_scanned,
        'returned_hits_lower_bound': lower_bound,
        'any_hit_truncation': truncated,
        'complete': complete,
    }
    public_coverage = {
        'schema_version': SCHEMA_VERSION,
        'batch_data_rows_scanned': batch_count,
        'cumulative_data_rows_scanned': total_scanned,
        'cumulative_hits_lower_bound': lower_bound,
        'any_hit_truncation': truncated,
        'selected_tab_grid_rows_scanned': complete,
        'other_tabs_searched': False,
        'all_supplier_folders_searched': False,
        'revision_value_externally_verified_by_this_function': False,
        'revision_token_consistency_checked': True,
        'original_sheet_contents_unchanged_proven': False,
        'source_writes': 0,
    }
    result = {
        'privacy_classification': 'PRIVATE_SCAN_RESULT_NEVER_LOG',
        'public_coverage': public_coverage,
        'public_summary': anonymous['public_summary'],
        'public_search_summary': matched,
        'private_cursor': cursor,
        'private_details_returned': False,
    }
    if include_private_hits:
        url = ('https://docs.google.com/spreadsheets/d/'
               +source['spreadsheet_id']+'/edit')
        review = inspect_selected_connector_sheet_pages_for_review(
            manifest=manifest, search=search,
            reviewer_context=reviewer_context,
            source_labels=[source['supplier_label']],
            sheet_gid_by_url={url:source['sheet_gid']},
            max_hits=max_hits,
        )
        result['private_review'] = review
        result['private_details_returned'] = True
    return result


def public_scan_progress(result):
    """Extract only anonymous counts; caller never prints private_cursor."""
    if (not isinstance(result, dict)
            or result.get('privacy_classification')
            != 'PRIVATE_SCAN_RESULT_NEVER_LOG'):
        raise ValueError('not a private scan result')
    return {
        'public_coverage': dict(result['public_coverage']),
        'public_summary': dict(result['public_summary']),
        'public_search_summary': dict(result['public_search_summary']),
        'private_details_returned': False,
    }
