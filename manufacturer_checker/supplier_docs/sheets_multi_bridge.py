"""Private, bounded Google Sheets v4 -> common supplier normalization bridge.

Use an already-authorized *read-only* Google Sheets client, with a PRIVATE,
explicitly selected list of up to 5 spreadsheet tabs. The module never
acquires credentials, enumerates Drive folders, writes source files, uploads
source data, or starts background jobs.

ValueRenderOption=FORMULA intentionally preserves raw numeric types and raw
formulas; the existing conservative parser never evaluates those formulas.
"""
import re

from .drive_delta import FILE_ID
from .multi_source_readonly import (
    MAX_SOURCES, normalize_selected_sources, search_selected_sources,
    validate_source_lookup,
)
from .parser import DOCUMENT_TYPES
from .readers import sheets_values, sheets_visible_tabs

SCHEMA_VERSION = 'manual-multi-sheet-v1'
MODE = 'manual_readonly'
END_COLUMN = 'O'
ROWS_PER_TAB = 40
MAX_READ_CELLS = MAX_SOURCES * ROWS_PER_TAB * 15
_TAB = re.compile(r"^[^!\r\n\x00-\x1f]{1,100}$")
_ALLOWED_TARGET_KEYS = frozenset({
    'spreadsheet_id', 'title', 'document_type', 'header_row',
})


def validate_multi_sheet_manifest(manifest):
    """Preflight all targets BEFORE calling an external API.

    No implicit all-tabs lookup or arbitrary A1 range, no flexible URLs.
    This returns a private sequence of explicit (id, title, type, header).
    """
    if (not isinstance(manifest, dict)
            or set(manifest) != {'schema_version', 'mode', 'targets'}
            or manifest['schema_version'] != SCHEMA_VERSION
            or manifest['mode'] != MODE
            or not isinstance(manifest['targets'], list)
            or not 1 <= len(manifest['targets']) <= MAX_SOURCES):
        raise ValueError('invalid approved cross-supplier read manifest')

    result = []
    seen = set()
    for target in manifest['targets']:
        if (not isinstance(target, dict)
                or not {'spreadsheet_id', 'title', 'document_type'} <= set(target)
                or not set(target) <= _ALLOWED_TARGET_KEYS):
            raise ValueError('invalid selected sheet target')
        file_id = target['spreadsheet_id']
        title = target['title']
        doc_type = target['document_type']
        hrow = target.get('header_row')
        if (not isinstance(file_id, str) or not FILE_ID.fullmatch(file_id)
                or not isinstance(title, str) or not _TAB.fullmatch(title)
                or not title.strip()
                or not isinstance(doc_type, str)
                or doc_type not in DOCUMENT_TYPES
                or (hrow is not None and
                    (type(hrow) is not int or not 1 <= hrow <= 20))
                or (file_id, title) in seen):
            raise ValueError('invalid, hidden or duplicate sheet selection')
        seen.add((file_id, title))
        result.append((file_id, title, doc_type, hrow))
    if len(result) * ROWS_PER_TAB * 15 > MAX_READ_CELLS:
        raise ValueError('aggregate cell read budget exceeded')
    return result


def inspect_selected_google_sheets(sheets_service, *, manifest, search=None):
    """Read explicit visible tabs and search only those records in memory.

    public_summary contains anonymous counts, bounded read metadata and
    no source IDs, names, JANs, ASINs, prices or source URLs.
    Private results must NEVER be stored in public CI logs or GitHub.
    """
    planned = validate_multi_sheet_manifest(manifest)
    if search is not None:
        if not isinstance(search, dict) or set(search) != {'field', 'query'}:
            raise ValueError('invalid selected cross-supplier search')
        validate_source_lookup(search['field'], search['query'])

    # Preflight ALL tab visibility before reading any cells.
    # Reuse metadata for the same spreadsheet so queries remain bounded.
    visible_by_file = {}
    for file_id, title, _, _ in planned:
        if file_id not in visible_by_file:
            visible_by_file[file_id] = sheets_visible_tabs(
                sheets_service, spreadsheet_id=file_id, max_tabs=100)
        if title not in visible_by_file[file_id]:
            raise ValueError('selected sheet is missing or hidden')

    specs = []
    formulas = 0
    for file_id, title, doc_type, header_row in planned:
        escaped = title.replace("'", "''")
        rows = sheets_values(
            sheets_service, spreadsheet_id=file_id,
            sheet_range=f"'{escaped}'!A1:{END_COLUMN}{ROWS_PER_TAB}")
        formulas += sum(
            isinstance(cell, str) and cell.lstrip().startswith('=')
            for row in rows for cell in row)
        specs.append({
            'source_file_id': file_id,
            'source_url': f'https://docs.google.com/spreadsheets/d/{file_id}/edit',
            'source_sheet': title,
            'document_type': doc_type,
            'header_row': header_row,
            'rows': rows,
        })

    normalized = normalize_selected_sources(specs)
    # The offline module's api_calls=0 does not describe this bridge.
    # Correct it explicitly, so audit reports distinguish offline runs.
    summary = dict(normalized['public_summary'])
    summary.update({
        'schema_version': SCHEMA_VERSION,
        'mode': MODE,
        'sheets_metadata_reads': len(visible_by_file),
        'sheets_values_reads': len(planned),
        'api_calls': len(visible_by_file) + len(planned),
        'formula_cells_present': formulas,
        'read_window_rows_per_tab': ROWS_PER_TAB,
        'read_window_last_column': END_COLUMN,
        'source_writes': 0,
        'review_required': True,
    })
    result = {
        'public_summary': summary,
        'private_normalized_docs': normalized['private_normalized_docs'],
    }
    if search is not None:
        found = search_selected_sources(normalized, **search)
        result['public_search_summary'] = found['public_summary']
        result['private_hits'] = found['private_hits']
    return result
