"""Synthetic Excel files only, produced in disposable temporary directories.

Never use real supplier spreadsheets, Drive downloads, secrets, external APIs,
Amazon account data or executable VBA.
"""
import json
from pathlib import Path
import tempfile
import unittest

from openpyxl import Workbook

from supplier_docs.local_excel_bridge import (
    SCHEMA_VERSION, MODE, inspect_selected_local_excel,
    validate_excel_manifest,
)


JAN_A = '0000000000017'
JAN_B = '0000000000024'
ASIN_A = 'B0TEST0001'
ASIN_B = 'B0TEST0002'


def write_book(path, title, rows, *, hidden=False):
    wb = Workbook()
    ws = wb.active
    ws.title = title
    for row in rows:
        ws.append(row)
    if hidden:
        wb.create_sheet('VISIBLE')
        ws.sheet_state = 'hidden'
    wb.save(path)
    wb.close()


def manifest():
    return {
        'schema_version': SCHEMA_VERSION,
        'mode': MODE,
        'targets': [
            {'relative_path': 'company_alpha.xlsx',
             'sheet_name': '見積もり', 'document_type': 'quote_response'},
            {'relative_path': 'company_beta.xlsx',
             'sheet_name': '新田ゼラチン', 'document_type': 'quote_response'},
            {'relative_path': 'company_gamma.xlsm',
             'sheet_name': 'GEX', 'document_type': 'quote_response'},
            {'relative_path': 'company_delta.xlsx',
             'sheet_name': 'シート1', 'document_type': 'quote_request'},
        ],
    }


class LocalExcelBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write_book(self.root / 'company_alpha.xlsx', '見積もり', [
            ['メーカー', '', '商品名', '商品名（Amazon）', '',
             'JAN', '品番', '上代(税抜）', '発注単位', '下代(税抜）'],
            ['架空企業甲', '', '架空テープ', '架空テープ',
             '', JAN_A, 'MODEL-001', 850, '1個', 600],
        ])
        write_book(self.root / 'company_beta.xlsx', '新田ゼラチン', [
            ['', '商品名', '', '商品名（Amazon）', 'ASIN',
             'JAN', '卸値', '発注単位', '卸値（税込）'],
            ['', '架空ゼラチン', '', '架空ゼラチン', ASIN_A,
             JAN_A, '', '6個', 500],
        ])
        write_book(self.root / 'company_gamma.xlsm', 'GEX', [
            ['メーカー', '商品名', '商品名（Amazon）', 'ASIN',
             'JAN', '', '発注単位\n（ケース/カートン）',
             'BOX入り数×ケース内ボックス数', '卸価格',
             '税込仕入れ値\n'],
            ['架空企業乙', '架空フィルター', '架空フィルター',
             ASIN_B, JAN_B, '', '1ケース', '4x3',
             '=42*10', '=42*11'],
        ])
        write_book(self.root / 'company_delta.xlsx', 'シート1', [
            [], [], ['商品名', 'JAN', 'ASIN'],
            ['架空マスク', 1234567890123, ASIN_B],
        ])

    def inspect(self, *, conf=None, search=None):
        return inspect_selected_local_excel(
            root_dir=self.root, manifest=conf or manifest(), search=search)

    def test_four_excel_workbooks_and_macro_extension_are_read_only(self):
        outcome = self.inspect()
        status = outcome['public_summary']
        self.assertEqual(status['source_count'], 4)
        self.assertEqual(status['record_count'], 4)
        self.assertEqual(status['local_files_read'], 4)
        self.assertEqual(status['local_tabs_read'], 4)
        self.assertEqual(status['cells_maximum_requested'], 2400)
        self.assertEqual(status['formula_cells_present'], 2)
        self.assertEqual(status['api_calls'], 0)
        self.assertEqual(status['source_writes'], 0)
        self.assertFalse(status['purchase_allowed'])
        self.assertFalse(status['profit_calculation_allowed'])
        docs = outcome['private_normalized_docs']
        self.assertEqual([v['header_row'] for v in docs], [1, 1, 1, 3])
        self.assertEqual(docs[0]['records'][0]['model_number'], 'MODEL-001')
        self.assertIn('JAN_NUMERIC_CELL', [
            code for warning in docs[3]['warnings']
            for code in warning['codes']
        ])

    def test_exact_cross_company_jan_lookup_has_original_excel_row(self):
        result = self.inspect(search={'field': 'jan', 'query': JAN_A})
        summary = result['public_search_summary']
        self.assertEqual(summary['hits_returned'], 2)
        self.assertFalse(summary['all_supplier_folders_searched'])
        self.assertEqual([r['source_index'] for r in result['private_hits']], [0, 1])
        self.assertEqual([r['source_row'] for r in result['private_hits']], [2, 2])
        self.assertEqual(result['private_origin_manifest'][0]['relative_path'],
                         'company_alpha.xlsx')

    def test_model_and_asin_are_shared_with_sheets_lookup(self):
        outcome = self.inspect(search={'field': 'model', 'query': 'MODEL-001'})
        self.assertEqual(outcome['public_search_summary']['hits_returned'], 1)
        outcome = self.inspect(search={'field': 'asin', 'query': ASIN_B})
        self.assertEqual(outcome['public_search_summary']['hits_returned'], 2)

    def test_ambiguous_cost_headers_not_approved(self):
        outcome = self.inspect()
        self.assertEqual(outcome['public_summary']
                         ['ambiguous_field_source_counts'], {'cost_amount': 1})
        self.assertFalse(outcome['private_normalized_docs'][1]['records'][0]
                         ['cost_present'])

    def test_formula_text_is_not_evaluated(self):
        result = self.inspect()
        gamma = result['private_normalized_docs'][2]['records'][0]
        self.assertEqual(gamma['cost_tax_mode'], 'unknown')
        self.assertFalse(gamma['cost_present'])
        self.assertFalse(result['public_summary']['profit_calculation_allowed'])

    def test_public_summary_has_no_identifiers_names_paths_or_prices(self):
        result = self.inspect(search={'field': 'jan', 'query': JAN_A})
        public = json.dumps(
            [result['public_summary'], result['public_search_summary']],
            ensure_ascii=False)
        for secret in ('company_alpha', 'company_beta', '架空', JAN_A,
                       JAN_B, ASIN_A, ASIN_B, 'MODEL-001', '600', '850',
                       str(self.root), 'GEX'):
            self.assertNotIn(secret, public)

    def test_unsupported_file_and_path_traversal_fail_closed(self):
        bad_paths = ['../secret.xlsx', '/etc/passwd', 'notes.csv',
                     'dir\\file.xlsx', 'company_delta.exe', '', 'C:\\secret.xlsm']
        for bad in bad_paths:
            candidate = manifest()
            candidate['targets'][0]['relative_path'] = bad
            with self.subTest(value=bad), self.assertRaises(ValueError):
                self.inspect(conf=candidate)

    def test_symlink_path_outside_root_rejected(self):
        other = Path(self.temp.name).parent / 'unrelated-target-file.xlsx'
        shortcut = self.root / 'shortcut.xlsx'
        shortcut.symlink_to(other)
        candidate = manifest()
        candidate['targets'][0]['relative_path'] = shortcut.name
        with self.assertRaises(ValueError):
            self.inspect(conf=candidate)

    def test_invisible_sheet_and_missing_sheet_rejected(self):
        write_book(self.root / 'hidden.xlsx', 'RESTRICTED',
                   [['商品名', 'JAN'], ['架空', JAN_A]], hidden=True)
        for filename, sheet in [('hidden.xlsx', 'RESTRICTED'),
                                ('company_alpha.xlsx', 'UNKNOWN')]:
            candidate = manifest()
            candidate['targets'][0]['relative_path'] = filename
            candidate['targets'][0]['sheet_name'] = sheet
            with self.subTest(sheet=sheet), self.assertRaises(ValueError):
                self.inspect(conf=candidate)

    def test_corrupt_and_oversize_files_fail_closed(self):
        bad = self.root / 'corrupt.xlsx'
        bad.write_bytes(b'NOT AN EXCEL ZIP FILE')
        candidate = manifest()
        candidate['targets'][0]['relative_path'] = bad.name
        with self.assertRaises(ValueError):
            self.inspect(conf=candidate)

    def test_invalid_lookup_rejected_before_file_read(self):
        invalids = [('jan', '0'), ('unknown', 'something'), ('asin', 'B0')]
        for field, query in invalids:
            with self.subTest(field=field, query=query), self.assertRaises(ValueError):
                self.inspect(search={'field': field, 'query': query})

    def test_empty_and_unrecognized_workbooks_do_not_hide_coverage(self):
        write_book(self.root / 'empty.xlsx', 'EMPTY', [])
        candidate = manifest()
        candidate['targets'][1]['relative_path'] = 'empty.xlsx'
        candidate['targets'][1]['sheet_name'] = 'EMPTY'
        result = self.inspect(conf=candidate)
        self.assertEqual(result['public_summary']
                         ['source_status_counts']['empty'], 1)
        self.assertFalse(result['public_summary']['all_selected_windows_parsed'])

        write_book(self.root / 'unknown.xlsx', 'UNKNOWN', [
            ['日付', '概要'], ['2026', '商品らしい文字列'],
        ])
        candidate['targets'][1]['relative_path'] = 'unknown.xlsx'
        candidate['targets'][1]['sheet_name'] = 'UNKNOWN'
        result = self.inspect(conf=candidate)
        self.assertEqual(result['public_summary']
                         ['source_status_counts']['needs_review'], 1)

    def test_max_five_sources_and_duplicate_preflight(self):
        config = manifest()
        config['targets'].append(dict(config['targets'][0]))
        with self.assertRaises(ValueError):
            validate_excel_manifest(config)
        config['targets'].append(dict(config['targets'][0]))
        with self.assertRaises(ValueError):
            validate_excel_manifest(config)
        config = manifest()
        config['targets'][0]['unexpected'] = 1
        with self.assertRaises(ValueError):
            validate_excel_manifest(config)

    def test_nonnumeric_header_and_malformed_manifest_rejected(self):
        for bad in (None, [], {'mode': MODE}):
            with self.subTest(value=repr(bad)), self.assertRaises(ValueError):
                validate_excel_manifest(bad)
        candidate = manifest()
        candidate['targets'][0]['header_row'] = True
        with self.assertRaises(ValueError):
            validate_excel_manifest(candidate)


if __name__ == '__main__':
    unittest.main()
