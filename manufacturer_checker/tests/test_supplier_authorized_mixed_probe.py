"""Synthetic Excel + mocked Sheets v4 service; no real auth or vendor data."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from openpyxl import Workbook

from supplier_docs.authorized_mixed_probe import inspect_authorized_mixed_sources
from supplier_docs.local_excel_bridge import (
    SCHEMA_VERSION as EXCEL_SCHEMA, MODE as EXCEL_MODE,
)
from supplier_docs.sheets_multi_bridge import (
    SCHEMA_VERSION as SHEETS_SCHEMA, MODE as SHEETS_MODE,
)

JAN = '0000000000017'
ASIN = 'B0TEST0001'
SHEET_ID = 'FAKE_SHEET_001'


class Reply:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return deepcopy(self.value)


class FakeSheetService:
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
                'title': 'Sheet1', 'hidden': False, 'sheetType': 'GRID'
            }}]})
        self.calls.append('values')
        return Reply({'values': [['商品名', 'JAN', 'ASIN'],
                                 ['架空Sheets商品', JAN, ASIN]]})


def excel_config():
    return {
        'schema_version': EXCEL_SCHEMA,
        'mode': EXCEL_MODE,
        'targets': [{
            'relative_path': 'approved.xlsx',
            'sheet_name': 'Quote',
            'document_type': 'quote_request',
        }],
    }


def sheets_config():
    return {
        'schema_version': SHEETS_SCHEMA,
        'mode': SHEETS_MODE,
        'targets': [{
            'spreadsheet_id': SHEET_ID,
            'title': 'Sheet1',
            'document_type': 'quote_request',
        }],
    }


class AuthorizedMixedProbeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.workbook = self.root / 'approved.xlsx'
        wb = Workbook()
        sheet = wb.active
        sheet.title = 'Quote'
        sheet.append(['商品名', 'JAN', 'ASIN'])
        sheet.append(['架空Excel商品', JAN, ASIN])
        wb.save(self.workbook)
        wb.close()
        self.original_bytes = self.workbook.read_bytes()
        self.service = FakeSheetService()
        self.factory_calls = 0

    def service_factory(self):
        self.factory_calls += 1
        return self.service

    def probe(self, ex=None, sh=None, search=None, factory=None):
        return inspect_authorized_mixed_sources(
            root_dir=self.root,
            excel_manifest=ex if ex is not None else excel_config(),
            sheets_manifest=sh if sh is not None else sheets_config(),
            service_factory=factory if factory is not None else self.service_factory,
            search=search,
        )

    def test_valid_two_format_exact_jan_search(self):
        result = self.probe(search={'field': 'jan', 'query': JAN})
        self.assertEqual(result['public_summary']['source_kind_counts'],
                         {'excel': 1, 'sheets': 1})
        self.assertEqual(result['public_summary']['record_count'], 2)
        self.assertEqual(result['public_search_summary']['hits_returned'], 2)
        self.assertEqual(self.service.calls, ['metadata', 'values'])
        self.assertEqual(self.factory_calls, 1)
        self.assertEqual([h['source_row'] for h in result['private_hits']], [2, 2])
        self.assertFalse(result['public_summary']['profit_calculation_allowed'])

    def test_invalid_combined_limit_avoids_credentials(self):
        ex = excel_config()
        ex['targets'] = [
            dict(ex['targets'][0], sheet_name='Quote' + str(i))
            for i in range(4)
        ]
        sh = sheets_config()
        sh['targets'] = [
            dict(sh['targets'][0], title='Sheet' + str(i))
            for i in range(2)
        ]
        with self.assertRaises(ValueError):
            self.probe(ex=ex, sh=sh)
        self.assertEqual(self.factory_calls, 0)

    def test_invalid_search_before_local_and_google_reads(self):
        with self.assertRaises(ValueError):
            self.probe(search={'field': 'jan', 'query': 'bad'})
        self.assertEqual(self.factory_calls, 0)
        self.assertEqual(self.workbook.read_bytes(), self.original_bytes)

    def test_invalid_sheets_schema_before_credentials(self):
        sh = sheets_config()
        sh['targets'][0]['title'] = 'bad!A1'
        with self.assertRaises(ValueError):
            self.probe(sh=sh)
        self.assertEqual(self.factory_calls, 0)

    def test_missing_excel_file_fails_without_google_calls(self):
        ex = excel_config()
        ex['targets'][0]['relative_path'] = 'missing.xlsx'
        with self.assertRaises((OSError, ValueError)):
            self.probe(ex=ex)
        self.assertEqual(self.factory_calls, 0)
        self.assertEqual(self.service.calls, [])

    def test_missing_authorized_service_is_not_silent(self):
        with self.assertRaises(ValueError):
            self.probe(factory=lambda: None)
        self.assertEqual(self.service.calls, [])

    def test_private_fields_do_not_appear_in_public_aggregation(self):
        result = self.probe(search={'field': 'asin', 'query': ASIN})
        public = json.dumps(
            [result['public_summary'], result['public_search_summary']],
            ensure_ascii=False)
        for private in (JAN, ASIN, SHEET_ID, 'approved.xlsx',
                        '架空Excel商品', str(self.root)):
            self.assertNotIn(private, public)
        self.assertEqual(self.workbook.read_bytes(), self.original_bytes)

    def test_does_not_mutate_manifests_or_source_workbook(self):
        ex, sh = excel_config(), sheets_config()
        before = deepcopy((ex, sh))
        self.probe(ex=ex, sh=sh)
        self.assertEqual((ex, sh), before)
        self.assertEqual(self.workbook.read_bytes(), self.original_bytes)


if __name__ == '__main__':
    unittest.main()
