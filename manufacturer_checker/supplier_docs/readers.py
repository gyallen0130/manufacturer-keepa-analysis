"""File and Sheets-value adapters; never write to source files or Drive."""
import csv
import io
import re
from pathlib import Path


def local_rows(path, *, sheet_name=None, encoding=None, max_file_bytes=20_000_000):
    path = Path(path)
    if path.stat().st_size > max_file_bytes:
        raise ValueError('file too large for bounded parser')
    suffix = path.suffix.lower()
    if suffix in ('.xlsx', '.xlsm'):
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=False, keep_links=False)
        try:
            if sheet_name and sheet_name not in wb.sheetnames:
                raise ValueError('selected sheet not found')
            ws = wb[sheet_name] if sheet_name else wb.worksheets[0]
            return list(ws.iter_rows(values_only=True)), ws.title
        finally:
            wb.close()
    if suffix in ('.csv', '.tsv'):
        raw = path.read_bytes()
        if encoding:
            text = raw.decode(encoding)
        else:
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                text = raw.decode('cp932')
        return list(csv.reader(io.StringIO(text), delimiter='\t' if suffix == '.tsv' else ',')), ''
    raise ValueError('supported extensions: .xlsx, .xlsm, .csv, .tsv')


def sheets_values(service, *, spreadsheet_id, sheet_range):
    """Read only: caller supplies an authenticated Sheets v4 client and explicit A1 range.

    FORMULA preserves raw numeric cell types and returns formulas as text.
    Never evaluate formula strings or infer lost leading zeros for numeric identifiers.
    """
    # Reject unbounded A:A / A1:A and overly broad scans before any API call.
    # Only a finite, explicit rectangular range is accepted here.
    pat = r"^(?:'(?:[^']|'')+'|[^'!]+)![\$]?([A-Za-z]{1,3})[\$]?(\d+):[\$]?([A-Za-z]{1,3})[\$]?(\d+)$"
    match = re.fullmatch(pat, str(sheet_range or ''))
    if not spreadsheet_id or not match:
        raise ValueError('sheet id and a finite sheet!A1:B100 range are required')
    col1,row1,col2,row2 = match.groups()
    def colnum(text):
        out = 0
        for ch in text.upper():
            out = out * 26 + ord(ch) - ord('A') + 1
        return out
    start_col, end_col = colnum(col1), colnum(col2)
    start_row, end_row = int(row1), int(row2)
    if (start_row < 1 or end_row < start_row or start_col < 1
            or end_col < start_col or (end_row - start_row + 1) * (end_col - start_col + 1) > 50000):
        raise ValueError('range must be ordered, positive, and no more than 50000 cells')
    result = (service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=sheet_range,
        valueRenderOption='FORMULA',
    ).execute())
    return result.get('values', [])


def sheets_visible_tabs(service, *, spreadsheet_id, max_tabs=20):
    """List only visible GRID sheet names via read-only Sheets metadata.

    Names are for internal routing, not for logging or public reports.  No
    Drive folder discovery, permissions change or range read is performed.
    """
    if not isinstance(spreadsheet_id, str) or not spreadsheet_id.strip():
        raise ValueError('a spreadsheet ID is required')
    if type(max_tabs) is not int or not 1 <= max_tabs <= 100:
        raise ValueError('max_tabs must be 1..100')
    response = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields='sheets(properties(title,sheetType,hidden))',
    ).execute()
    sheets = response.get('sheets', [])
    if not isinstance(sheets, list) or len(sheets) > max_tabs:
        raise ValueError('sheet count exceeds configured maximum')
    titles = []
    for item in sheets:
        prop = item.get('properties', {})
        if (prop.get('sheetType', 'GRID') != 'GRID'
                or prop.get('hidden', False)):
            continue
        title = prop.get('title')
        if not isinstance(title, str) or not title.strip() or '!' in title:
            raise ValueError('invalid visible sheet title')
        if title in titles:
            raise ValueError('duplicate visible sheet title')
        titles.append(title)
    return titles


def sheets_selected_tabs_summary(service, *, spreadsheet_id, tab_document_types,
                                 max_rows_per_tab=40, end_col='L', max_tabs=10):
    """Summarize explicitly selected visible tabs, never exposing source values.

    The caller MUST choose a supported document type for each tab.  No
    automatic 'all tabs' discovery, write API or blanket Drive access.
    The 50k-cell budget applies to the entire requested batch, not per tab.
    """
    from collections import Counter
    from .parser import DOCUMENT_TYPES, SCHEMA_VERSION, parse_rows

    if (not isinstance(tab_document_types, dict)
            or not tab_document_types or len(tab_document_types) > max_tabs):
        raise ValueError('select 1..max_tabs tabs explicitly')
    if type(max_rows_per_tab) is not int or not 2 <= max_rows_per_tab <= 20000:
        raise ValueError('max_rows_per_tab must be 2..20000')
    if type(max_tabs) is not int or not 1 <= max_tabs <= 20:
        raise ValueError('max_tabs must be 1..20')
    if not isinstance(end_col, str) or not re.fullmatch(r'[A-Z]{1,3}', end_col):
        raise ValueError('end_col must be uppercase A..ZZZ')
    ncols = 0
    for char in end_col:
        ncols = ncols * 26 + (ord(char) - ord('A') + 1)
    if ncols > 26 or len(tab_document_types) * ncols * max_rows_per_tab > 50000:
        raise ValueError('selected tabs exceed bounded cell budget')
    for title, doc_type in tab_document_types.items():
        if (not isinstance(title, str) or not title.strip() or '!' in title
                or doc_type not in DOCUMENT_TYPES):
            raise ValueError('each selected tab needs its exact name and document type')
    available = sheets_visible_tabs(service, spreadsheet_id=spreadsheet_id, max_tabs=100)
    if any(title not in available for title in tab_document_types):
        raise ValueError('a selected tab is missing or hidden')

    results = []
    total_count = 0
    risk_counts = Counter()
    warning_counts = Counter()
    for index, (title, doc_type) in enumerate(tab_document_types.items(), 1):
        quoted = title.replace("'", "''")
        rows = sheets_values(
            service, spreadsheet_id=spreadsheet_id,
            sheet_range=f"'{quoted}'!A1:{end_col}{max_rows_per_tab}")
        entry = {'tab_index': index, 'document_type': doc_type}
        if not rows or not any(str(cell).strip() for row in rows for cell in row
                               if cell is not None):
            entry.update(status='empty', record_count=0)
            results.append(entry)
            continue
        try:
            parsed = parse_rows(rows, document_type=doc_type, source_sheet=title)
        except ValueError as exc:
            if str(exc) != 'no reliable header: select document type or header_row':
                raise
            entry.update(status='needs_review', record_count=0)
            results.append(entry)
            continue
        count = parsed['summary']['record_count']
        total_count += count
        risk_counts.update(parsed['summary']['risk_counts'])
        warning_counts.update(
            code for warning in parsed['warnings'] for code in warning['codes'])
        entry.update(
            status='parsed', record_count=count,
            inferred_fields=parsed['summary'].get('inferred_fields', []),
            has_ambiguous_columns=any(
                'AMBIGUOUS_COLUMNS' in warning['codes']
                for warning in parsed['warnings']))
        results.append(entry)
    return {
        'schema_version': SCHEMA_VERSION,
        'total_record_count': total_count,
        'risk_counts': dict(sorted(risk_counts.items())),
        'warning_code_counts': dict(sorted(warning_counts.items())),
        'tabs': results,
    }
