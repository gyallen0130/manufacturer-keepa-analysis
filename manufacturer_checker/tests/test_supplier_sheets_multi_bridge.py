"""Offline fake Google Sheets v4 service; no private data or network."""
import copy
import json
import unittest

from supplier_docs.sheets_multi_bridge import (
    SCHEMA_VERSION, inspect_selected_google_sheets,
    validate_multi_sheet_manifest,
)


JAN_A = '0000000000017'
JAN_B = '0000000000024'
ASIN_A = 'B0TEST0001'
ASIN_B = 'B0TEST0002'
IDS = ('FAKE_SHEET_VENDOR_0001', 'FAKE_SHEET_VENDOR_0002',
       'FAKE_SHEET_VENDOR_0003', 'FAKE_SHEET_VENDOR_0004')
TABS = ('見積もり', '新田ゼラチン', 'GEX', 'シート1')


class Response:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return copy.deepcopy(self.data)


class SheetsFake:
    def __init__(self, hidden=None):
        self.calls = []
        self.hidden = set(hidden or ())
        self.rows = {
            IDS[0]: [
                ['メーカー', '', '商品名', '商品名（Amazon）', '',
                 'JAN', '品番', '上代(税抜）', '発注単位', '下代(税抜）'],
                ['架空メーカー甲', '', '架空テープA', '架空テープA',
                 '', JAN_A, 'TEST-100', 800, '10本', 510],
            ],
            IDS[1]: [
                ['', '商品名', '', '商品名（Amazon）', 'ASIN',
                 'JAN', '卸値', '発注単位', '卸値（税込）'],
                ['', '架空ゼラチンA', '', '架空ゼラチンA', ASIN_A,
                 JAN_A, '', '6個', 540],
            ],
            IDS[2]: [
                ['メーカー', '商品名', '商品名（Amazon）', 'ASIN',
                 'JAN', '', '発注単位\n（ケース/カートン）',
                 'BOX入り数×ケース内ボックス数', '卸価格',
                 '税込仕入れ値\n', '仕入数'],
                ['架空メーカー乙', '架空フィルター', '架空フィルター',
                 ASIN_B, JAN_B, '', '1ケース', '4x3',
                 '=42*10', '=42*11', 1],
            ],
            IDS[3]: [
                [], [],
                ['商品名', 'JAN', 'ASIN'],
                ['架空マスク', 100000000017, ASIN_B],
            ],
        }

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **kwargs):
        file_id = kwargs['spreadsheetId']
        if 'fields' in kwargs:
            self.calls.append(('metadata', file_id))
            return Response({'sheets': [
                {'properties': {
                    'title': TABS[IDS.index(file_id)],
                    'hidden': file_id in self.hidden,
                    'sheetType': 'GRID',
                }},
            ]})
        self.calls.append(('values', file_id, kwargs['range'],
                           kwargs.get('valueRenderOption')))
        return Response({'values': self.rows[file_id]})


def approved():
    return {
        'schema_version': SCHEMA_VERSION,
        'mode': 'manual_readonly',
        'targets': [
            {'spreadsheet_id': IDS[i], 'title': TABS[i],
             'document_type': ('quote_request' if i == 3 else 'quote_response')}
            for i in range(4)
        ],
    }


class SheetsMultiBridgeTests(unittest.TestCase):
    def test_four_suppliers_read_only_typed_values_to_common_fields(self):
        svc = SheetsFake()
        result = inspect_selected_google_sheets(svc, manifest=approved())
        s = result['public_summary']
        self.assertEqual(s['source_count'], 4)
        self.assertEqual(s['record_count'], 4)
        self.assertEqual(s['api_calls'], 8)
        self.assertEqual(s['sheets_metadata_reads'], 4)
        self.assertEqual(s['sheets_values_reads'], 4)
        self.assertEqual(s['source_writes'], 0)
        self.assertFalse(s['profit_calculation_allowed'])
        docs = result['private_normalized_docs']
        self.assertEqual([x['header_row'] for x in docs], [1, 1, 1, 3])
        self.assertEqual(docs[0]['records'][0]['model_number'], 'TEST-100')
        self.assertEqual(docs[3]['records'][0]['source_row'], 4)

    def test_all_metadata_preflight_before_first_value_read(self):
        svc = SheetsFake()
        inspect_selected_google_sheets(svc, manifest=approved())
        self.assertEqual([x[0] for x in svc.calls],
                         ['metadata'] * 4 + ['values'] * 4)
        self.assertEqual([x[3] for x in svc.calls[4:]], ['FORMULA'] * 4)
        self.assertTrue(all(x[2].endswith("'!A1:O40")
                            for x in svc.calls[4:]))

    def test_hidden_tab_fails_without_any_values_reads(self):
        svc = SheetsFake(hidden={IDS[3]})
        with self.assertRaises(ValueError):
            inspect_selected_google_sheets(svc, manifest=approved())
        self.assertTrue(all(c[0] == 'metadata' for c in svc.calls))

    def test_invalid_manifest_does_not_call_google(self):
        configs = []
        for bad in ({'schema_version': 'invalid'},
                    {'unexpected': 1}):
            c = approved()
            c.update(bad)
            configs.append(c)
        other = approved()
        other['targets'] += [other['targets'][0]] * 2
        configs.append(other)
        duplicated = approved()
        duplicated['targets'].append(duplicated['targets'][0])
        configs.append(duplicated)
        for field, value in [('spreadsheet_id', 'NOT VALID'),
                             ('header_row', 21), ('document_type', 'auto'),
                             ('title', 'bad!tab')]:
            bad = approved()
            bad['targets'][0][field] = value
            configs.append(bad)
        for config in configs:
            svc = SheetsFake()
            with self.subTest(config=str(config)[:20]):
                with self.assertRaises(ValueError):
                    inspect_selected_google_sheets(svc, manifest=config)
                self.assertEqual(svc.calls, [])

    def test_jan_exact_search_across_two_sources_with_provenance(self):
        svc = SheetsFake()
        res = inspect_selected_google_sheets(
            svc, manifest=approved(), search={'field': 'jan', 'query': JAN_A})
        self.assertEqual(res['public_search_summary']['hits_returned'], 2)
        self.assertEqual(
            [r['source_index'] for r in res['private_hits']], [0, 1])
        self.assertEqual(
            [r['source_row'] for r in res['private_hits']], [2, 2])
        self.assertFalse(res['public_search_summary']['product_identity_confirmed'])

    def test_ignored_price_formulas_do_not_enable_profit(self):
        res = inspect_selected_google_sheets(SheetsFake(), manifest=approved())
        self.assertEqual(res['public_summary']['formula_cells_present'], 2)
        yoshida = res['private_normalized_docs'][2]['records'][0]
        self.assertFalse(yoshida['cost_present'])
        self.assertEqual(yoshida['cost_tax_mode'], 'unknown')
        self.assertFalse(res['public_summary']['profit_calculation_allowed'])

    def test_numeric_jan_preserves_risk_of_lost_zero(self):
        res = inspect_selected_google_sheets(SheetsFake(), manifest=approved())
        ito = res['private_normalized_docs'][3]
        self.assertIn('JAN_NUMERIC_CELL',
                      [code for w in ito['warnings'] for code in w['codes']])
        self.assertEqual(ito['records'][0]['decision'], 'needs_confirmation')

    def test_no_raw_values_in_public(self):
        res = inspect_selected_google_sheets(
            SheetsFake(), manifest=approved(),
            search={'field': 'asin', 'query': ASIN_B})
        public = json.dumps([res['public_summary'],
                             res['public_search_summary']], ensure_ascii=False)
        for hidden in (JAN_A, JAN_B, ASIN_A, ASIN_B, '架空マスク',
                       'TEST-100', '510', IDS[0], 'GEX', '540'):
            self.assertNotIn(hidden, public)

    def test_no_api_writes_and_query_validation_before_cells(self):
        svc = SheetsFake()
        with self.assertRaises(ValueError):
            inspect_selected_google_sheets(svc, manifest=approved(),
                                           search={'field': 'jan', 'query': 123})
        self.assertFalse(any(c[0] == 'values' for c in svc.calls))
        self.assertTrue(all(c[0] in ('metadata', 'values') for c in svc.calls))

    def test_source_rows_unchanged_and_read_budget_capped(self):
        svc = SheetsFake()
        original = copy.deepcopy(svc.rows)
        inspect_selected_google_sheets(svc, manifest=approved())
        self.assertEqual(svc.rows, original)
        self.assertEqual(validate_multi_sheet_manifest(approved())[0][1],
                         TABS[0])

    def test_search_record_scope_is_selected_not_all_folders(self):
        res = inspect_selected_google_sheets(
            SheetsFake(), manifest=approved(),
            search={'field': 'product', 'query': '架空マスク'})
        self.assertEqual(res['public_search_summary']['sources_searched'], 4)
        self.assertFalse(
            res['public_search_summary']['all_supplier_folders_searched'])

    def test_original_file_ids_never_in_aggregate_even_on_failure(self):
        res = inspect_selected_google_sheets(SheetsFake(), manifest=approved())
        pub = json.dumps(res['public_summary'])
        for file_id in IDS:
            self.assertNotIn(file_id, pub)

    def test_realistic_duplicate_wako_cost_headers_report_ambiguity(self):
        result = inspect_selected_google_sheets(SheetsFake(), manifest=approved())
        self.assertEqual(result['public_summary']
                         ['ambiguous_field_source_counts'], {'cost_amount': 1})
        record = result['private_normalized_docs'][1]['records'][0]
        self.assertFalse(record['cost_present'])
        self.assertEqual(record['cost_tax_mode'], 'unknown')
        self.assertFalse(result['public_summary']['profit_calculation_allowed'])



if __name__ == '__main__':
    unittest.main()
