"""Supplier parser regression tests use entirely synthetic business data."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from openpyxl import Workbook
from supplier_docs import parse_rows
from supplier_docs.readers import local_rows, sheets_values


class SupplierDocumentTests(unittest.TestCase):
    def test_manufacturer_list_unlabeled_first_column(self):
        rows = [
            ['', 'メーカーコード', 'カテゴリー', '備考'],
            ['株式会社サンプル', '1234000', '美容雑貨', '一部EC不可'],
            ['株式会社別社', '4321000', '雑貨', ''],
        ]
        result = parse_rows(rows, document_type='manufacturer_list', source_file_id='fake-id')
        self.assertEqual(result['header_row'], 1)
        self.assertEqual(result['summary']['record_count'], 2)
        self.assertEqual(result['records'][0]['manufacturer_name_raw'], '株式会社サンプル')
        self.assertEqual(result['records'][0]['manufacturer_code'], '1234000')
        self.assertIn('CHANNEL_RESTRICTION', result['records'][0]['risk_codes'])

    def test_quote_header_auto_detect_and_inheritance(self):
        rows = [
            ['お見積もり一覧'],
            ['メーカー', '', '商品名', '商品名（Amazon）', '', 'JAN', '品番', '上代(税抜）', '発注単位', '下代(税抜）'],
            ['株式会社サンプル', 'ケース単位', 'テスト製品', 'Amazon商品', 'B012345678', '0012345678901', 'X-1', 1000, 12, 650],
            ['', '', 'テスト製品2', '別商品', 'B087654321', '12345678', 'X-2', 2000, 6, 900],
            ['', '', '', '', '', '', '', '', '', ''],
            ['', '', '製品3', '', '', '87654321', '', '', 1, 100],
        ]
        result = parse_rows(rows, document_type='quote_response')
        self.assertEqual(result['header_row'], 2)
        self.assertEqual(result['summary']['record_count'], 3)
        r0, r1, r2 = result['records']
        self.assertEqual(r1['manufacturer_name_raw'], '株式会社サンプル')
        self.assertEqual(r2['manufacturer_name_raw'], '')
        self.assertEqual(r0['jan_string'], '0012345678901')
        self.assertEqual(r0['asin_candidate'], 'B012345678')
        self.assertIn('ASIN_UNLABELED_CANDIDATE', result['warnings'][0]['codes'])
        self.assertEqual(r0['cost_tax_mode'], 'excluded')
        self.assertTrue(r0['cost_present'])
        self.assertNotIn('cost_amount', r0)

    def test_conditional_profit_text_not_black(self):
        rows = [
            ['メーカー', '商品名', '利益'],
            ['サンプル', '商品A', '黒字'],
            ['', '商品B', '黒字（条件次第で赤字）'],
            ['', '商品C', '微黒字'],
            ['', '商品D', '赤字'],
        ]
        x = parse_rows(rows, document_type='quote_response')
        got = [r['source_profit_status'] for r in x['records']]
        self.assertEqual(got, ['black', 'conditional_or_unclassified', 'slight_black', 'red'])
        self.assertIn('CONDITIONAL_PROFIT', x['records'][1]['risk_codes'])
        self.assertTrue(all(r['decision'] == 'needs_confirmation' for r in x['records']))

    def test_unlabeled_profit_note_flagged(self):
        rows = [
            ['メーカー', '商品名', '', '備考'],
            ['A', 'B', '黒字（Amazon直販で赤字）', ''],
        ]
        x = parse_rows(rows, document_type='quote_response')
        self.assertEqual(x['records'][0]['source_profit_status'], 'conditional_or_unclassified')
        self.assertIn('UNLABELED_PROFIT_TEXT', x['warnings'][0]['codes'])

    def test_supply_and_price_restrictions(self):
        rows = [
            ['メーカー', '品名', '備考'],
            ['会社A', '商品X', '美容ルート限定'],
            ['会社B', '商品Y', '定価販売でお願いします'],
            ['会社C', '商品Z', 'ジョンズブレンドECサイトは不可'],
        ]
        x = parse_rows(rows, document_type='catalog')
        self.assertIn('SUPPLY_RESTRICTION', x['records'][0]['risk_codes'])
        self.assertIn('PRICE_POLICY_NOTE', x['records'][1]['risk_codes'])
        self.assertIn('CHANNEL_RESTRICTION', x['records'][2]['risk_codes'])

    def test_ambiguous_cost_fields_fail_closed(self):
        rows = [
            ['メーカー', '商品名', '卸値', '卸値（税込）'],
            ['A', 'B', '500', '550'],
        ]
        x = parse_rows(rows, document_type='quote_response')
        self.assertNotIn('cost_amount', x['mapped_columns'])
        self.assertIn('AMBIGUOUS_COLUMNS', x['warnings'][0]['codes'])
        self.assertIn('COST_UNKNOWN', x['records'][0]['risk_codes'])

    def test_cost_hidden_by_default_and_explicitly_included(self):
        rows = [['メーカー', '商品名', '下代（税抜）', '備考'], ['架空社', '架空品', '1234', '極秘の条件']]
        hidden = parse_rows(rows, document_type='quote_response')
        visible = parse_rows(rows, document_type='quote_response', include_sensitive=True)
        self.assertNotIn('cost_amount', hidden['records'][0])
        self.assertNotIn('極秘', json.dumps(hidden, ensure_ascii=False))
        self.assertEqual(visible['records'][0]['cost_amount'], '1234')
        self.assertEqual(visible['records'][0]['notes'], '極秘の条件')

    def test_jan_numeric_warning_and_formula_rejection(self):
        rows = [['商品名', 'JAN'], ['商品A', 12345678], ['商品B', '=12345678'],
                ['商品C', '0012345678901'], ['商品D', '1.23E+12']]
        x = parse_rows(rows, document_type='catalog')
        self.assertEqual([x['records'][i]['jan_string'] for i in range(4)],
                         ['12345678', '', '0012345678901', ''])
        self.assertTrue(any('JAN_NUMERIC_CELL' in warn['codes'] for warn in x['warnings']))
        self.assertTrue(any('JAN_FORMULA' in warn['codes'] for warn in x['warnings']))

    def test_renamed_price_revision_not_wholesale_cost(self):
        rows = [['JANコード', '対象製品一覧', '変更前価格（税抜）', '変更後価格（税抜）'],
                ['0012345678901', '架空商品', 900, 1000]]
        x = parse_rows(rows, document_type='price_revision')
        self.assertEqual(x['records'][0]['product_name_raw'], '架空商品')
        self.assertFalse(x['records'][0]['cost_present'])

    def test_headers_and_bad_ranges(self):
        with self.assertRaises(ValueError):
            parse_rows([['foo', 'bar']], document_type='catalog')
        with self.assertRaises(ValueError):
            parse_rows([['商品名'], ['A']], document_type='wrong-type')
        with self.assertRaises(ValueError):
            parse_rows([['商品名'], ['A']], document_type='catalog', header_row=99)

    def test_local_xlsx_and_csv_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = root / 'sample.xlsx'
            wb = Workbook()
            ws = wb.active
            ws.title = '商品表'
            ws.append(['商品名', 'JAN'])
            ws.append(['サンプル', '0012345678901'])
            wb.save(path)
            rows, tab = local_rows(path, sheet_name='商品表')
            self.assertEqual(tab, '商品表')
            self.assertEqual(rows[1][1], '0012345678901')
            self.assertEqual(parse_rows(rows, document_type='catalog')['records'][0]['jan_string'], '0012345678901')
            self.assertTrue(path.exists())
            csv_path = root / 'sample.csv'
            csv_path.write_bytes('商品名,JAN\n商品A,12345678\n'.encode('cp932'))
            crows, _ = local_rows(csv_path)
            self.assertEqual(crows[1][0], '商品A')

    def test_sheets_adapter_read_only(self):
        response = Mock()
        response.execute.return_value = {'values': [['商品名', 'JAN'], ['架空商品', '0012345678901']]}
        api = Mock()
        api.spreadsheets.return_value.values.return_value.get.return_value = response
        data = sheets_values(api, spreadsheet_id='fake-id', sheet_range="'見積もり'!A1:L20")
        self.assertEqual(data[1][1], '0012345678901')
        api.spreadsheets.return_value.values.return_value.get.assert_called_once_with(
            spreadsheetId='fake-id', range="'見積もり'!A1:L20", valueRenderOption='FORMULA')
        with self.assertRaises(ValueError):
            sheets_values(api, spreadsheet_id='fake-id', sheet_range='A:L')

    def test_sheets_numeric_jan_and_formula_are_flagged(self):
        response = Mock()
        response.execute.return_value = {
            'values': [
                ['商品名', 'JAN'],
                ['架空商品A', 12345678],
                ['架空商品B', '=12345678'],
                ['架空商品C', '0012345678901'],
            ]
        }
        api = Mock()
        api.spreadsheets.return_value.values.return_value.get.return_value = response
        rows = sheets_values(api, spreadsheet_id='fake-id', sheet_range="'架空'!A1:B4")
        x = parse_rows(rows, document_type='catalog')
        self.assertEqual([r['jan_string'] for r in x['records']],
                         ['12345678', '', '0012345678901'])
        codes = [c for warning in x['warnings'] for c in warning['codes']]
        self.assertIn('JAN_NUMERIC_CELL', codes)
        self.assertIn('JAN_FORMULA', codes)
        api.spreadsheets.return_value.values.return_value.get.assert_called_once_with(
            spreadsheetId='fake-id', range="'架空'!A1:B4", valueRenderOption='FORMULA')

    def test_cli_default_redacted_and_exclusive_write(self):
        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / 'sample.csv'
            file.write_text('メーカー,商品名,下代(税抜),備考\n架空社,商品A,1234,極秘\n', encoding='utf-8')
            cmd = [sys.executable, '-m', 'supplier_docs.cli', '--input', str(file),
                   '--document-type', 'quote_response']
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            self.assertNotIn('1234', result.stdout)
            self.assertNotIn('極秘', result.stdout)
            out = Path(d) / 'output.json'
            cmdout = cmd + ['--include-sensitive', '--output', str(out)]
            subprocess.run(cmdout, capture_output=True, text=True, check=True)
            self.assertIn('1234', out.read_text(encoding='utf-8'))
            dup = subprocess.run(cmdout, capture_output=True, text=True)
            self.assertNotEqual(dup.returncode, 0)


if __name__ == '__main__':
    unittest.main()
