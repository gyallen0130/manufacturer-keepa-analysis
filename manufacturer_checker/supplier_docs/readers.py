"""File and Sheets-value adapters; never write to source files or Drive."""
import csv
import io
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

    FORMATTED_VALUE is used for display strings. Do not infer leading zeros
    for identifier cells that were already stored incorrectly as numbers.
    """
    if not spreadsheet_id or not sheet_range or '!' not in sheet_range:
        raise ValueError('sheet id and a bounded sheet!A1 range are required')
    result = (service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=sheet_range,
        valueRenderOption='FORMATTED_VALUE',
    ).execute())
    return result.get('values', [])
