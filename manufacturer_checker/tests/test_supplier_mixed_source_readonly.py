"""Synthetic Excel+Sheets mixed lookup; no real supplier data or network."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from openpyxl import Workbook

from supplier_docs.local_excel_bridge import (
    SCHEMA_VERSION as EXCEL_SCHEMA, MODE as EXCEL_MODE,
    inspect_selected_local_excel,
)
from supplier_docs.sheets_multi_bridge import (
    SCHEMA_VERSION as SHEETS_SCHEMA, MODE as SHEETS_MODE,
    inspect_selected_google_sheets,
)
from supplier_docs.mixed_source_readonly import combine_selected_source_results
from supplier_docs.row_labeled_candidates import VERSION

JAN = '0000000000017'
ASIN = 'B0TEST0001'
FILE_ID = 'FAKE_MIXED_SHEETS_001'


class Response:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return deepcopy(self.data)


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
            return Response({'sheets': [
                {'properties': {'title': 'Main', 'hidden': False,
                                'sheetType': 'GRID'}}
            ]})
        self.calls.append('values')
        return Response({'values': [
            ['商品名', 'JAN', 'ASIN'],
            ['架空Sheets商品', JAN, ASIN],
        ]})


def tiered_rows():
    data = [[] for _ in range(17)]
    data[11] = ['', '商品コード']
    data[12] = ['', '', '', '', '商品名・POSコード・ITFコード']
    data[13] = ['', '', '', '', '', '', '', '入数', '', '', '価格']
    data[14] = ['', '', '', '', '', '', '', '', '', '', '価格']
    data[16] = ['', '', '', 'POSコード：', JAN, 'ITFコード：', '-']
    return data


def make_excel(root):
    file = Path(root) / 'fake.xlsm'
    wb = Workbook()
    simple = wb.active
    simple.title = 'Normal'
    simple.append(['商品名', 'JAN', 'ASIN'])
    simple.append(['架空Excel商品', JAN, ASIN])
    complex_sheet = wb.create_sheet('Tiered')
    for line in tiered_rows():
        complex_sheet.append(line)
    wb.save(file)
    wb.close()
    return file


def excel_manifest():
    return {
        'schema_version': EXCEL_SCHEMA, 'mode': EXCEL_MODE,
        'targets': [
            {'relative_path': 'fake.xlsm', 'sheet_name': 'Normal',
             'document_type': 'quote_request'},
            {'relative_path': 'fake.xlsm', 'sheet_name': 'Tiered',
             'document_type': 'catalog',
             'row_labeled_mapping': {
                 'version': VERSION, 'data_start_row': 16,
                 'fields': {'pos_candidate': {
                     'label_column': 4, 'value_column': 5}},
             }},
        ],
    }


def sheets_manifest():
    return {
        'schema_version': SHEETS_SCHEMA, 'mode': SHEETS_MODE,
        'targets': [
            {'spreadsheet_id': FILE_ID, 'title': 'Main',
             'document_type': 'quote_request'},
        ],
    }


class MixedSourceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = temp.name
        self.file = make_excel(temp.name)
        self.fake = FakeSheets()
        self.before = self.file.read_bytes()

    def sources(self):
        excel = inspect_selected_local_excel(
            root_dir=self.root, manifest=excel_manifest())
        sheets = inspect_selected_google_sheets(
            self.fake, manifest=sheets_manifest())
        return excel, sheets

    def test_two_real_connectors_use_shared_private_query(self):
        excel, sheets = self.sources()
        result = combine_selected_source_results(
            [excel, sheets], search={'field': 'jan', 'query': JAN})
        self.assertEqual(result['public_summary']['source_kind_counts'],
                         {'excel': 2, 'sheets': 1})
        self.assertEqual(result['public_summary']['source_count'], 3)
        self.assertEqual(result['public_summary']['record_count'], 3)
        self.assertEqual(result['public_summary']['records_by_identifier_kind']['jan'], 2)
        self.assertEqual(result['public_summary']['records_by_identifier_kind']['pos'], 1)
        self.assertEqual(result['public_search_summary']['hits_returned'], 2)
        self.assertEqual([h['source_index'] for h in result['private_hits']], [0, 2])
        self.assertEqual(result['private_source_kinds'],
                         ['excel', 'excel', 'sheets'])
        self.assertEqual(result['public_summary']['api_calls'], 2)
        self.assertEqual(self.fake.calls, ['metadata', 'values'])

    def test_pos_review_does_not_imply_jan_or_product_identity(self):
        excel, sheets = self.sources()
        merged = combine_selected_source_results(
            [excel, sheets], search={'field': 'pos', 'query': JAN})
        self.assertEqual(merged['public_search_summary']['hits_returned'], 1)
        self.assertEqual(merged['private_hits'][0]['source_index'], 1)
        self.assertEqual(merged['public_summary']['source_status_counts']
                         ['labeled_review'], 1)
        self.assertFalse(merged['public_summary']['all_selected_windows_parsed'])
        self.assertFalse(merged['public_summary']['profit_calculation_allowed'])
        self.assertFalse(merged['public_summary']['purchase_allowed'])
        self.assertFalse(merged['public_search_summary']['product_identity_confirmed'])

    def test_source_files_not_modified_or_saved_by_merger(self):
        excel, sheets = self.sources()
        combine_selected_source_results([excel, sheets])
        self.assertEqual(self.file.read_bytes(), self.before)

    def test_public_summary_never_prints_private_values(self):
        excel, sheets = self.sources()
        output = combine_selected_source_results(
            [excel, sheets], search={'field': 'jan', 'query': JAN})
        raw = json.dumps([output['public_summary'],
                          output['public_search_summary']], ensure_ascii=False)
        for private in (JAN, ASIN, FILE_ID, 'fake.xlsm', '架空', self.root):
            self.assertNotIn(private, raw)

    def test_cannot_duplicate_one_adapter_or_omit_other(self):
        excel, sheets = self.sources()
        for bad in ([excel, excel], [sheets, sheets], [excel], [sheets]):
            with self.subTest(n=len(bad)), self.assertRaises(ValueError):
                combine_selected_source_results(bad)

    def test_mismatched_source_count_rejected(self):
        excel, sheets = self.sources()
        excel['public_summary']['source_count'] = 3
        with self.assertRaises(ValueError):
            combine_selected_source_results([excel, sheets])

    def test_unverified_profit_or_source_writes_rejected(self):
        for tamper in ({'source_writes': 1},
                       {'profit_calculation_allowed': True},
                       {'purchase_allowed': True},
                       {'api_calls': 100}):
            excel, sheets = self.sources()
            excel['public_summary'].update(tamper)
            with self.subTest(tamper=tamper), self.assertRaises(ValueError):
                combine_selected_source_results([excel, sheets])

    def test_wrong_original_row_provenance_rejected(self):
        excel, sheets = self.sources()
        excel['private_normalized_docs'][0]['records'][0]['source_row'] = 101
        with self.assertRaises(ValueError):
            combine_selected_source_results([excel, sheets])

    def test_invalid_search_rejected(self):
        excel, sheets = self.sources()
        for query in (['bad'], {'field': 'jan', 'query': 'x'},
                      {'field': 'unknown', 'query': 'sample'}):
            with self.subTest(query=query), self.assertRaises(ValueError):
                combine_selected_source_results(
                    [excel, sheets], search=query)

    def test_over_five_tabs_rejected(self):
        excel, sheets = self.sources()
        excel['private_normalized_docs'] = [
            deepcopy(excel['private_normalized_docs'][0]) for _ in range(5)]
        for i, doc in enumerate(excel['private_normalized_docs']):
            doc['source_sheet'] = 'Example' + str(i)
            for rec in doc['records']:
                rec['source_sheet'] = doc['source_sheet']
        excel['public_summary']['source_count'] = 5
        with self.assertRaises(ValueError):
            combine_selected_source_results([excel, sheets])

    def test_private_source_reference_remains_traceable(self):
        excel, sheets = self.sources()
        mixed = combine_selected_source_results(
            [excel, sheets], search={'field': 'asin', 'query': ASIN})
        self.assertEqual(mixed['public_search_summary']['hits_returned'], 2)
        self.assertEqual([r['source_row'] for r in mixed['private_hits']], [2, 2])
        self.assertEqual(len(mixed['private_source_kinds']), 3)


if __name__ == '__main__':
    unittest.main()
