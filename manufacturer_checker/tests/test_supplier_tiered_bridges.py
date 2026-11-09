"""Synthetic-only Sheets and Excel tiered mapping bridge integration."""
import json
from pathlib import Path
import tempfile
import unittest

from openpyxl import Workbook

from supplier_docs.sheets_multi_bridge import (
    SCHEMA_VERSION as SHEETS_SCHEMA, MODE as SHEETS_MODE,
    inspect_selected_google_sheets,
)
from supplier_docs.local_excel_bridge import (
    SCHEMA_VERSION as EXCEL_SCHEMA, MODE as EXCEL_MODE,
    inspect_selected_local_excel,
)
from supplier_docs.tiered_header_mapping import MAPPING_VERSION


JAN = '0000000000017'
FILE_ID = 'FAKE_SOURCE_TIERED_001'
TAB = 'Tiered'


def rows():
    return [
        [],
        ['商品名'],
        ['', 'JAN'],
        ['', '', '価格'],
        ['架空商品A', JAN, 300],
        ['架空商品B', 100000000017, '=1+1'],
    ]


def tiered():
    return {
        'version': MAPPING_VERSION, 'header_rows': [2, 3, 4],
        'data_start_row': 5,
        'fields': {
            'product_name_raw': {'row': 2, 'column': 1},
            'jan_string': {'row': 3, 'column': 2},
        },
    }


class Reply:
    def __init__(self, obj):
        self.obj = obj

    def execute(self):
        return self.obj


class FakeSheets:
    def __init__(self):
        self.calls = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **kwargs):
        if 'fields' in kwargs:
            self.calls.append('metadata')
            return Reply({'sheets': [{
                'properties': {'title': TAB, 'hidden': False,
                               'sheetType': 'GRID'},
            }]})
        self.calls.append('values')
        return Reply({'values': rows()})


class TieredBridgesTests(unittest.TestCase):
    def sheets_manifest(self, mapping=None):
        return {
            'schema_version': SHEETS_SCHEMA, 'mode': SHEETS_MODE,
            'targets': [{'spreadsheet_id': FILE_ID, 'title': TAB,
                         'document_type': 'quote_response',
                         'tiered_mapping': mapping if mapping is not None
                         else tiered()}],
        }

    def test_sheets_read_only_mapped_review_with_exact_lookup(self):
        fake = FakeSheets()
        result = inspect_selected_google_sheets(
            fake, manifest=self.sheets_manifest(),
            search={'field': 'jan', 'query': JAN})
        self.assertEqual(fake.calls, ['metadata', 'values'])
        self.assertEqual(result['public_summary']
                         ['source_status_counts']['mapped_review'], 1)
        self.assertEqual(result['public_search_summary']['hits_returned'], 1)
        self.assertEqual(result['public_summary']['api_calls'], 2)
        self.assertFalse(result['public_summary']['profit_calculation_allowed'])

    def test_invalid_sheets_mapping_rejected_before_any_api_call(self):
        manifest = self.sheets_manifest()
        manifest['targets'][0]['tiered_mapping']['fields']['cost_amount'] = {
            'row': 4, 'column': 3,
        }
        fake = FakeSheets()
        with self.assertRaises(ValueError):
            inspect_selected_google_sheets(fake, manifest=manifest)
        self.assertEqual(fake.calls, [])

    def test_excel_valid_mapping_private_source_and_no_write(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'approved.xlsx'
            book = Workbook()
            sheet = book.active
            sheet.title = TAB
            for row in rows():
                sheet.append(row)
            book.save(path)
            book.close()
            before = path.read_bytes()
            manifest = {
                'schema_version': EXCEL_SCHEMA, 'mode': EXCEL_MODE,
                'targets': [{
                    'relative_path': 'approved.xlsx', 'sheet_name': TAB,
                    'document_type': 'quote_response',
                    'tiered_mapping': tiered(),
                }],
            }
            result = inspect_selected_local_excel(
                root_dir=root, manifest=manifest,
                search={'field': 'jan', 'query': JAN})
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(result['public_summary']
                             ['source_status_counts']['mapped_review'], 1)
            self.assertEqual(result['public_search_summary']['hits_returned'], 1)
            self.assertEqual(result['public_summary']['source_writes'], 0)
            self.assertEqual(result['public_summary']['api_calls'], 0)
            public = json.dumps([result['public_summary'],
                                 result['public_search_summary']],
                                ensure_ascii=False)
            for token in (JAN, '架空商品A', 'approved.xlsx', root, '300'):
                self.assertNotIn(token, public)

    def test_excel_bad_mapping_rejected_before_file_check(self):
        with tempfile.TemporaryDirectory() as root:
            manifest = {
                'schema_version': EXCEL_SCHEMA, 'mode': EXCEL_MODE,
                'targets': [{
                    'relative_path': 'nonexistent.xlsx', 'sheet_name': TAB,
                    'document_type': 'quote_response',
                    'tiered_mapping': {**tiered(), 'data_start_row': 3},
                }],
            }
            with self.assertRaisesRegex(ValueError, 'invalid explicit'):
                inspect_selected_local_excel(root_dir=root, manifest=manifest)


if __name__ == '__main__':
    unittest.main()
