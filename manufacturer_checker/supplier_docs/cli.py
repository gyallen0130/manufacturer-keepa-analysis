"""Offline supplier document inspection CLI. By default no financial values emitted."""
import argparse
import json
import sys
from .parser import DOCUMENT_TYPES, parse_rows
from .readers import local_rows, sheets_values


def main(argv=None):
    p = argparse.ArgumentParser(description='Read-only, conservative supplier document parser')
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--input', help='local .xlsx/.xlsm/.csv/.tsv file')
    mode.add_argument('--sheets-id', help='Google Sheets id (requires preconfigured ADC with read-only scope)')
    p.add_argument('--document-type', required=True, choices=sorted(DOCUMENT_TYPES))
    p.add_argument('--sheet-name', help='local Excel sheet (otherwise first sheet)')
    p.add_argument('--sheet-range', help="bounded Sheets A1 range, e.g. '見積もり'!A1:L300")
    p.add_argument('--header-row', type=int, help='1-based heading row; otherwise auto-detect')
    p.add_argument('--source-url', default='', help='original document link, optional')
    p.add_argument('--include-sensitive', action='store_true', help='include purchase prices and notes in local output')
    p.add_argument('--output', help='new, local JSON file; existing files are never overwritten')
    args = p.parse_args(argv)
    if args.include_sensitive and not args.output:
        p.error('--include-sensitive requires an explicit local --output')
    if args.sheets_id:
        if not args.sheet_range:
            p.error('--sheets-id requires --sheet-range')
        import google.auth
        from googleapiclient.discovery import build
        cred, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'])
        svc = build('sheets', 'v4', credentials=cred, cache_discovery=False)
        rows = sheets_values(svc, spreadsheet_id=args.sheets_id, sheet_range=args.sheet_range)
        source_sheet = args.sheet_range.split('!', 1)[0].strip("'")
        file_id = args.sheets_id
    else:
        rows, source_sheet = local_rows(args.input, sheet_name=args.sheet_name)
        file_id = ''
    result = parse_rows(rows, document_type=args.document_type,
                        source_file_id=file_id, source_url=args.source_url,
                        source_sheet=source_sheet, header_row=args.header_row,
                        include_sensitive=args.include_sensitive)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        # Exclusive creation + owner-only mode avoids accidental overwrite or broad sharing.
        import os
        fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            file.write(payload)
        print('Saved local JSON; source documents were not modified.', file=sys.stderr)
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
