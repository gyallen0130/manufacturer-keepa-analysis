"""Offline, bounded .xlsx/.xlsm -> multi-supplier normalization/search.

An authorized user supplies a PRIVATE local input directory and explicit
relative workbook paths, tab names and document types. Never discovers
folders, reads unselected tabs, evaluates formulas, executes VBA, writes
back to sources, or calls Google/Keepa/SP-API.

Only public_summary is appropriate for logs. All source names and product
records remain PRIVATE and should not be committed to GitHub.
"""
from contextlib import ExitStack
import hashlib
from pathlib import Path
import re
import zipfile

from .multi_source_readonly import (
    MAX_SOURCES, normalize_selected_sources, search_selected_sources,
    validate_source_lookup,
)
from .parser import DOCUMENT_TYPES
from .tiered_header_mapping import validate_tiered_mapping_schema
from .row_labeled_candidates import validate_row_label_mapping

SCHEMA_VERSION = 'manual-local-excel-v1'
MODE = 'manual_local_excel_readonly'
MAX_FILE_BYTES = 20_000_000
MAX_TOTAL_BYTES = 50_000_000
MAX_TABS_PER_FILE = 100
MAX_ROWS = 40
MAX_COLS = 15
_TARGET_KEYS = frozenset({
    'relative_path', 'sheet_name', 'document_type', 'header_row',
    'tiered_mapping', 'row_labeled_mapping',
})
_SHEET = re.compile(r'^[^\x00-\x1f]{1,100}$')
_ALLOWED_SUFFIXES = frozenset(('.xlsx', '.xlsm'))


def validate_excel_manifest(manifest):
    """Preflight all requested file/tab selections before opening any file."""
    if (not isinstance(manifest, dict)
            or set(manifest) != {'schema_version', 'mode', 'targets'}
            or manifest['schema_version'] != SCHEMA_VERSION
            or manifest['mode'] != MODE
            or not isinstance(manifest['targets'], list)
            or not 1 <= len(manifest['targets']) <= MAX_SOURCES):
        raise ValueError('invalid explicit Excel selection manifest')
    checked = []
    selected = set()
    for target in manifest['targets']:
        if (not isinstance(target, dict)
                or not {'relative_path', 'sheet_name', 'document_type'} <= set(target)
                or not set(target) <= _TARGET_KEYS):
            raise ValueError('invalid Excel selection')
        name = target['relative_path']
        sheet = target['sheet_name']
        kind = target['document_type']
        header = target.get('header_row')
        if (not isinstance(name, str) or not name or len(name) > 300
                or '\\' in name or any(ord(x) < 32 for x in name)
                or not isinstance(sheet, str) or not _SHEET.fullmatch(sheet)
                or not sheet.strip()
                or not isinstance(kind, str) or kind not in DOCUMENT_TYPES
                or (header is not None and
                    (type(header) is not int or not 1 <= header <= 20))):
            raise ValueError('invalid file name, tab or document type')
        path = Path(name)
        if (path.is_absolute() or '..' in path.parts
                or path.suffix.lower() not in _ALLOWED_SUFFIXES):
            raise ValueError('only selected relative .xlsx/.xlsm paths allowed')
        identifier = (str(path), sheet)
        if identifier in selected:
            raise ValueError('duplicate workbook tab selection')
        tiered_mapping = target.get('tiered_mapping')
        row_labeled_mapping = target.get('row_labeled_mapping')
        if tiered_mapping is not None and row_labeled_mapping is not None:
            raise ValueError('only one review mapping is allowed')
        if row_labeled_mapping is not None:
            validate_row_label_mapping(row_labeled_mapping)
            if header is not None:
                raise ValueError('row-label mapping conflicts with header row')
        if tiered_mapping is not None:
            validate_tiered_mapping_schema(tiered_mapping)
            if header is not None:
                raise ValueError('cannot mix single header with tiered mapping')
        selected.add(identifier)
        checked.append((path, sheet, kind, header, tiered_mapping, row_labeled_mapping))
    return checked


def inspect_selected_local_excel(*, root_dir, manifest, search=None):
    """Read only A1:O40 from each chosen visible worksheet and normalize.

    The root folder must already contain files supplied through an
    authorized private transfer. The module never downloads Drive data.
    Files are opened read_only=True, data_only=False, keep_links=False:
    formula text is not evaluated and VBA macros are never run.
    """
    selected = validate_excel_manifest(manifest)
    if search is not None:
        if not isinstance(search, dict) or set(search) != {'field', 'query'}:
            raise ValueError('invalid Excel lookup')
        validate_source_lookup(search['field'], search['query'])
    root = Path(root_dir)
    if not root.is_dir():
        raise ValueError('private input root must be an existing directory')
    root_resolved = root.resolve(strict=True)
    paths = []
    total_bytes = 0
    for relative, tab, kind, header, tiered_mapping, row_labeled_mapping in selected:
        child = root / relative
        if child.is_symlink():
            raise ValueError('selected file cannot be a symlink')
        path = child.resolve(strict=True)
        if not path.is_relative_to(root_resolved) or not path.is_file():
            raise ValueError('workbook must remain inside private root')
        size = path.stat().st_size
        total_bytes += size
        if (size > MAX_FILE_BYTES or total_bytes > MAX_TOTAL_BYTES
                or not zipfile.is_zipfile(path)):
            raise ValueError('invalid or oversized Excel workbook')
        paths.append((path, relative, tab, kind, header, tiered_mapping, row_labeled_mapping))

    from openpyxl import load_workbook

    sources = []
    origins = []
    formula_count = 0
    unique_files = set()
    with ExitStack() as stack:
        opened = {}
        # Open and validate EVERY target tab first. No cell values are read
        # if any workbook is invalid, hidden or missing a selected worksheet.
        for path, relative, tab, kind, header, tiered_mapping, row_labeled_mapping in paths:
            if path not in opened:
                wb = load_workbook(
                    path, read_only=True, data_only=False, keep_links=False)
                stack.callback(wb.close)
                if len(wb.worksheets) > MAX_TABS_PER_FILE:
                    raise ValueError('too many Excel tabs')
                opened[path] = wb
                unique_files.add(path)
            workbook = opened[path]
            if tab not in workbook.sheetnames:
                raise ValueError('selected Excel tab missing')
            worksheet = workbook[tab]
            if worksheet.sheet_state != 'visible':
                raise ValueError('hidden Excel tab cannot be scanned')

        for path, relative, tab, kind, header, tiered_mapping, row_labeled_mapping in paths:
            ws = opened[path][tab]
            rows = [list(row) for row in ws.iter_rows(
                min_row=1, max_row=MAX_ROWS, min_col=1,
                max_col=MAX_COLS, values_only=True)]
            formula_count += sum(
                isinstance(v, str) and v.lstrip().startswith('=')
                for row in rows for v in row)
            source_token = hashlib.sha256(
                (str(relative) + '\n' + tab).encode('utf-8')
            ).hexdigest()[:32]
            sources.append({
                'source_file_id': 'LOCAL_' + source_token,
                'source_url': '',
                'source_sheet': tab,
                'document_type': kind,
                'header_row': header,
                'tiered_mapping': tiered_mapping,
                'row_labeled_mapping': row_labeled_mapping,
                'rows': rows,
            })
            origins.append({
                'relative_path': str(relative),
                'sheet_name': tab,
                'source_file_id': 'LOCAL_' + source_token,
            })

    normalized = normalize_selected_sources(sources)
    summary = dict(normalized['public_summary'])
    summary.update({
        'schema_version': SCHEMA_VERSION,
        'mode': MODE,
        'local_files_read': len(unique_files),
        'local_tabs_read': len(paths),
        'read_window_rows_per_tab': MAX_ROWS,
        'read_window_columns_per_tab': MAX_COLS,
        'cells_maximum_requested': len(paths) * MAX_ROWS * MAX_COLS,
        'formula_cells_present': formula_count,
        'api_calls': 0,
        'source_writes': 0,
        'review_required': True,
    })
    result = {
        'public_summary': summary,
        'private_normalized_docs': normalized['private_normalized_docs'],
        'private_origin_manifest': origins,
    }
    if search is not None:
        found = search_selected_sources(normalized, **search)
        result['public_search_summary'] = found['public_summary']
        result['private_hits'] = found['private_hits']
    return result
