"""On-demand, bounded supplier Sheets inspection for a trusted PRIVATE runner.

The caller selects every spreadsheet, tab and document type in a PRIVATE
manifest. No Drive folder discovery, Search, writes, Keepa, SP-API, persistence
or automatic order decisions. Metadata and values are only read after a
complete strict preflight. Outputs are split:
- public_summary: counts ONLY, safe for ordinary CI logging.
- private_inspections: sensitive parsed rows / prices, NEVER log, upload to
  public artifacts or return to untrusted workflows.

This function is not authentication: callers must independently authorize the
Google principal, repository/WIF identity and approved private manifest.
"""
import re

from .drive_delta import FILE_ID
from .parser import DOCUMENT_TYPES, parse_rows
from .readers import sheets_values, sheets_visible_tabs

SCHEMA = 'supplier-manual-sheets-read-v1'
MAX_FILES = 3
MAX_TABS_PER_FILE = 4
MAX_CELLS = 7200
ROWS_PER_TAB = 100
END_COLUMN = 'L'
_ALLOWED_MANIFEST_KEYS = frozenset({'schema_version', 'mode', 'targets'})
_ALLOWED_TARGET_KEYS = frozenset({'spreadsheet_id', 'tabs'})
_ALLOWED_TAB_KEYS = frozenset({'title', 'document_type'})
_TITLE = re.compile(r"^[^!\r\n\x00-\x1f]{1,100}$")


def validate_manual_sheet_manifest(manifest):
    """Validate *all* targets before any Google Sheets API calls.

    Deliberately no arbitrary row ranges or user-selected query syntax:
    every requested tab is capped at A1:L100, <= 7,200 cells total.
    """
    if (not isinstance(manifest, dict)
            or set(manifest) != _ALLOWED_MANIFEST_KEYS
            or manifest['schema_version'] != SCHEMA
            or manifest['mode'] != 'manual_readonly'
            or not isinstance(manifest['targets'], list)
            or not 1 <= len(manifest['targets']) <= MAX_FILES):
        raise ValueError('invalid private manual Sheets read manifest')
    planned = []
    unique_files = set()
    cells = 0
    for item in manifest['targets']:
        if (not isinstance(item, dict)
                or set(item) != _ALLOWED_TARGET_KEYS
                or not isinstance(item['spreadsheet_id'], str)
                or not FILE_ID.fullmatch(item['spreadsheet_id'])
                or item['spreadsheet_id'] in unique_files
                or not isinstance(item['tabs'], list)
                or not 1 <= len(item['tabs']) <= MAX_TABS_PER_FILE):
            raise ValueError('invalid or duplicate approved Sheets target')
        unique_files.add(item['spreadsheet_id'])
        approved_tabs = []
        titles = set()
        for tab in item['tabs']:
            if (not isinstance(tab, dict) or set(tab) != _ALLOWED_TAB_KEYS
                    or not isinstance(tab['title'], str)
                    or not _TITLE.fullmatch(tab['title'])
                    or not tab['title'].strip()
                    or tab['title'] in titles
                    or not isinstance(tab['document_type'], str)
                    or tab['document_type'] not in DOCUMENT_TYPES):
                raise ValueError('invalid or duplicate explicitly approved tab')
            titles.add(tab['title'])
            approved_tabs.append((tab['title'], tab['document_type']))
            cells += ROWS_PER_TAB * 12
        planned.append((item['spreadsheet_id'], approved_tabs))
    if cells > MAX_CELLS:
        raise ValueError('manual Sheets read exceeds aggregate API cell budget')
    return planned


def inspect_manual_approved_sheets(
        sheets_service, *, manifest, include_sensitive_records=False):
    """Return private normalized records in memory, log only public_summary.

    include_sensitive_records=True exposes parsed purchase cost and trade terms
    ONLY to the private return value. It does not affect public_summary.
    """
    if type(include_sensitive_records) is not bool:
        raise ValueError('sensitive records flag must be explicit boolean')
    planned = validate_manual_sheet_manifest(manifest)

    # Validate every tab is visible BEFORE reading any cell contents.
    for file_id, tabs in planned:
        visible = sheets_visible_tabs(
            sheets_service, spreadsheet_id=file_id, max_tabs=100)
        if any(title not in visible for title, _ in tabs):
            raise ValueError('an approved tab is missing or hidden')

    private_results = []
    record_count = risk_row_count = warning_count = needs_review = 0
    for file_id, tabs in planned:
        target_result = {'spreadsheet_id': file_id, 'tabs': []}
        for title, doc_type in tabs:
            a1 = f"'{title.replace(chr(39), chr(39)*2)}'!A1:{END_COLUMN}{ROWS_PER_TAB}"
            rows = sheets_values(
                sheets_service, spreadsheet_id=file_id, sheet_range=a1)
            if not rows or not any(
                    str(cell).strip() for row in rows for cell in row
                    if cell is not None):
                target_result['tabs'].append({
                    'title': title, 'document_type': doc_type,
                    'status': 'empty', 'records': [],
                })
                continue
            try:
                parsed = parse_rows(
                    rows, document_type=doc_type,
                    source_file_id=file_id, source_sheet=title,
                    max_rows=ROWS_PER_TAB,
                    include_sensitive=include_sensitive_records)
            except ValueError as error:
                if str(error) != 'no reliable header: select document type or header_row':
                    raise
                needs_review += 1
                target_result['tabs'].append({
                    'title': title, 'document_type': doc_type,
                    'status': 'needs_review', 'records': [],
                })
                continue
            records = parsed['records']
            record_count += len(records)
            risk_row_count += sum(bool(record['risk_codes']) for record in records)
            warning_count += len(parsed['warnings'])
            target_result['tabs'].append({
                'title': title,
                'document_type': doc_type,
                'status': 'parsed',
                'records': records,
                'warnings': parsed['warnings'],
            })
        private_results.append(target_result)

    return {
        'public_summary': {
            'schema_version': SCHEMA,
            'mode': 'manual_readonly',
            'approved_files': len(planned),
            'approved_tabs': sum(len(tabs) for _, tabs in planned),
            'normalized_records': record_count,
            'records_with_review_risks': risk_row_count,
            'warning_count': warning_count,
            'tabs_requiring_manual_review': needs_review,
            'source_write_operations': 0,
            'cloud_storage_writes': 0,
            'automatic_purchases': 0,
            'detailed_values_logged': False,
            'review_required': True,
        },
        'private_inspections': private_results,
    }
