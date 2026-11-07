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

    FORMULA preserves numeric cell types and returns formulas as text.
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
