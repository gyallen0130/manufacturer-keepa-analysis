"""Synthetic-only Sheets and Excel connector checks for row-labeled codes."""
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
from supplier_docs.row_labeled_candidates import VERSION

POS = '0000000000017'
ITF = '10000000000007'
ID = 'FAKE_ROW_LABELED_SHEET_001'
TAB = 'SampleTiered'


def rows():
    v = [[] for _ in range(18)]
    v[11] = ['', '商品コード']
    v[12] = ['', '', '', '', '商品名・POSコード・ITFコード']
    v[13] = ['', '', '', '', '', '', '', '入数', '', '', '価格']
    v[14] = ['', '', '', '', '', '', '', '', '', '', '価格']
    v[16] = ['', '', '', 'POSｺｰﾄﾞ：', POS, 'ITFｺｰﾄﾞ：', ITF]
    v[17] = ['', '', '', 'POSコード:', 1234567890123, 'ITFコード:', '=1+1']
    return v


def manual_mapping():
    return {
        'version': VERSION, 'data_start_row': 16,
        'fields': {
            'pos_candidate': {'label_column': 4, 'value_column': 5},
            'itf_candidate': {'label_column': 6, 'value_column': 7},
        },
    }


class Reply:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class SheetsFake:
    def __init__(self):
        self.calls = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **kwargs):
        if 'fields' in kwargs:
            self.calls.append('metadata')
            return Reply({'sheets': [{'properties': {
                'title': TAB, 'sheetType': 'GRID', 'hidden': False,
            }}]})
        self.calls.append('values')
        return Reply({'values': rows()})


class RowLabeledBridgesTests(unittest.TestCase):
    def sheets_manifest(self, manual=None):
        return {
            'schema_version': SHEETS_SCHEMA, 'mode': SHEETS_MODE,
            'targets': [{'spreadsheet_id': ID, 'title': TAB,
                         'document_type': 'catalog',
                         'row_labeled_mapping': (manual if manual is not None
                                                 else manual_mapping())}],
        }

    def excel_manifest(self, manual=None):
        return {
            'schema_version': EXCEL_SCHEMA, 'mode': EXCEL_MODE,
            'targets': [{'relative_path': 'fake.xlsx', 'sheet_name': TAB,
                         'document_type': 'catalog',
                         'row_labeled_mapping': (manual if manual is not None
                                                 else manual_mapping())}],
        }

    def test_sheets_pos_search_private_row_number(self):
        fake = SheetsFake()
        res = inspect_selected_google_sheets(
            fake, manifest=self.sheets_manifest(),
            search={'field': 'pos', 'query': POS})
        self.assertEqual(fake.calls, ['metadata', 'values'])
        self.assertEqual(res['public_summary']['records_with_pos_candidate'], 1)
        self.assertEqual(res['public_search_summary']['hits_returned'], 1)
        self.assertEqual(res['private_hits'][0]['source_row'], 17)
        self.assertFalse(res['public_search_summary']['product_identity_confirmed'])

    def test_excel_pos_itf_and_no_source_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / 'fake.xlsx'
            book = Workbook()
            sheet = book.active
            sheet.title = TAB
            for row in rows():
                sheet.append(row)
            book.save(file)
            book.close()
            before = file.read_bytes()
            result = inspect_selected_local_excel(
                root_dir=root, manifest=self.excel_manifest(),
                search={'field': 'itf', 'query': ITF})
            self.assertEqual(file.read_bytes(), before)
            self.assertEqual(result['public_summary']['source_status_counts']
                             ['labeled_review'], 1)
            self.assertEqual(result['public_summary']['records_with_itf_candidate'], 1)
            self.assertEqual(result['public_search_summary']['hits_returned'], 1)
            self.assertFalse(result['public_summary']['profit_calculation_allowed'])
            public = json.dumps(
                [result['public_summary'], result['public_search_summary']],
                ensure_ascii=False)
            for token in (POS, ITF, str(file), TAB):
                self.assertNotIn(token, public)

    def test_invalid_sheets_mapping_no_api_read(self):
        manual = manual_mapping()
        manual['fields']['cost_amount'] = {'label_column': 9, 'value_column': 10}
        fake = SheetsFake()
        with self.assertRaises(ValueError):
            inspect_selected_google_sheets(
                fake, manifest=self.sheets_manifest(manual))
        self.assertEqual(fake.calls, [])

    def test_invalid_excel_mapping_before_file_read(self):
        invalid = manual_mapping()
        invalid['fields']['pos_candidate']['value_column'] = 12
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                inspect_selected_local_excel(
                    root_dir=root, manifest=self.excel_manifest(invalid))

    def test_cannot_claim_jan_from_pos_candidate(self):
        fake = SheetsFake()
        result = inspect_selected_google_sheets(
            fake, manifest=self.sheets_manifest(),
            search={'field': 'jan', 'query': POS})
        self.assertEqual(result['public_search_summary']['hits_returned'], 0)
        self.assertEqual(result['public_search_summary']
                         ['sources_without_field_coverage'], 1)

    def test_conflicting_tiered_and_row_labels_preflight(self):
        manifest = self.sheets_manifest()
        manifest['targets'][0]['tiered_mapping'] = {'version': 'fake'}
        fake = SheetsFake()
        with self.assertRaises(ValueError):
            inspect_selected_google_sheets(fake, manifest=manifest)
        self.assertEqual(fake.calls, [])


if __name__ == '__main__':
    unittest.main()
