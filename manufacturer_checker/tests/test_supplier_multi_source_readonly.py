"""Synthetic multi-supplier templates based on inspected header STRUCTURES.

No actual source JANs, ASINs, manufacturers' products, quotes, Drive
records or prices are used. No network, credentials or workbook writes.
"""
import copy
import json
import unittest

from supplier_docs.multi_source_readonly import (
    normalize_selected_sources, search_selected_sources,
)


def fake_jan(prefix):
    numbers = [int(v) for v in prefix]
    check = (10 - sum(v * (3 if i % 2 else 1)
                      for i, v in enumerate(numbers)) % 10) % 10
    return prefix + str(check)


JAN_X = fake_jan('000000000001')
JAN_Y = fake_jan('000000000002')
JAN_Z = fake_jan('000000000003')
ASIN_X = 'B0TEST0001'
ASIN_Y = 'B0TEST0002'


def sources():
    """Four different original header layouts; only fake products and IDs."""
    return [
        {
            'source_file_id': 'FAKE_INOUE_001',
            'source_sheet': '見積もり',
            'source_url': 'https://example.invalid/private-inoue',
            'document_type': 'quote_response',
            'rows': [
                ['メーカー', '取引', '商品名', '商品名（Amazon）', '空欄',
                 'JAN', '品番', '上代(税抜）', '発注単位', '下代(税抜）'],
                ['架空会社甲', '可', '架空テープ小型', '架空テープ小型',
                 '', JAN_X, 'TEST-M001', 900, '10個', 600],
            ],
        },
        {
            'source_file_id': 'FAKE_WAKO_002',
            'source_sheet': '架空メーカー名',
            'source_url': 'https://example.invalid/private-wako',
            'document_type': 'quote_response',
            'rows': [
                ['', '商品名', '', '商品名（Amazon）', 'ASIN',
                 'JAN', '卸値', '発注単位', '卸値（税込）'],
                ['', '架空ゼラチンA', '', '架空ゼラチンA',
                 ASIN_X, JAN_X, '', '6袋', 650],
            ],
        },
        {
            'source_file_id': 'FAKE_YOSHIDA_003',
            'source_sheet': '架空水槽メーカー',
            'source_url': 'https://example.invalid/private-yoshida',
            'document_type': 'quote_response',
            'rows': [
                ['メーカー', '商品名', '商品名（Amazon）', 'ASIN',
                 'JAN', '空欄', '発注単位\n（ケース/カートン）',
                 'BOX入り数×ケース内ボックス数', '卸価格',
                 '税込仕入れ値\n', '仕入数'],
                ['架空会社乙', '架空フィルターA', '架空フィルターA',
                 ASIN_Y, JAN_Y, '', '1ケース', '4x3', 300, 330, 2],
            ],
        },
        {
            'source_file_id': 'FAKE_ITOU_004',
            'source_sheet': 'シート1',
            'source_url': 'https://example.invalid/private-itou',
            'document_type': 'quote_request',
            'rows': [
                [], [],
                ['商品名', 'JAN', 'ASIN'],
                ['架空マスクA', JAN_Z, ASIN_Y],
            ],
        },
    ]


class CrossSupplierReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.specs = sources()

    def test_four_source_templates_normalize_with_original_header_rows(self):
        result = normalize_selected_sources(self.specs)
        docs = result['private_normalized_docs']
        self.assertEqual(len(docs), 4)
        self.assertEqual([doc['header_row'] for doc in docs], [1, 1, 1, 3])
        self.assertEqual([doc['summary']['record_count'] for doc in docs], [1]*4)
        self.assertEqual(result['public_summary']['record_count'], 4)
        self.assertEqual(result['public_summary']['source_count'], 4)

    def test_model_numbers_preserved_for_vendor_independent_lookup(self):
        result = normalize_selected_sources(self.specs)
        self.assertEqual(result['private_normalized_docs'][0]
                         ['records'][0]['model_number'], 'TEST-M001')
        search = search_selected_sources(result, field='model',
                                         query='TEST-M001')
        self.assertEqual(search['public_summary']['hits_returned'], 1)
        self.assertEqual(search['private_hits'][0]['source_row'], 2)

    def test_same_jan_returns_two_candidates_not_confirmed_same_sku(self):
        result = normalize_selected_sources(self.specs)
        search = search_selected_sources(result, field='jan',
                                         query=JAN_X)
        self.assertEqual(search['public_summary']['hits_returned'], 2)
        self.assertFalse(search['public_summary']['product_identity_confirmed'])
        self.assertFalse(result['public_summary']['profit_calculation_allowed'])
        self.assertFalse(search['public_summary']['all_supplier_folders_searched'])
        self.assertEqual(
            [hit['source_index'] for hit in search['private_hits']], [0, 1])

    def test_jan_is_exact_not_substring(self):
        normalized = normalize_selected_sources(self.specs)
        search = search_selected_sources(
            normalized, field='jan', query=JAN_X[:-1])
        self.assertEqual(search['public_summary']['hits_returned'], 0)

    def test_asin_exact_and_private_row_location(self):
        result = normalize_selected_sources(self.specs)
        search = search_selected_sources(result, field='asin', query=ASIN_Y)
        self.assertEqual(search['public_summary']['hits_returned'], 2)
        self.assertEqual([hit['source_row'] for hit in search['private_hits']],
                         [2, 4])

    def test_product_name_partial_with_nfkc(self):
        normalized = normalize_selected_sources(self.specs)
        search = search_selected_sources(
            normalized, field='product_name_raw', query='架空マスク')
        self.assertEqual(search['public_summary']['hits_returned'], 1)
        self.assertEqual(search['private_hits'][0]['source_index'], 3)

    def test_manufacturer_tab_name_is_not_manufacturer_proof(self):
        result = normalize_selected_sources(self.specs)
        wako = result['private_normalized_docs'][1]
        self.assertEqual(wako['source_sheet'], '架空メーカー名')
        self.assertEqual(wako['records'][0]['manufacturer_name_raw'], '')
        self.assertEqual(
            search_selected_sources(result, field='manufacturer',
                                    query='架空メーカー')['public_summary']['hits_returned'],
            0)

    def test_unmapped_prices_and_case_size_not_guessed(self):
        result = normalize_selected_sources(self.specs)
        yoshida = result['private_normalized_docs'][2]
        self.assertNotIn('cost_amount', yoshida['mapped_columns'])
        self.assertNotIn('order_multiple', yoshida['mapped_columns'])
        self.assertFalse(yoshida['records'][0]['cost_present'])
        self.assertEqual(yoshida['records'][0]['decision'],
                         'needs_confirmation')
        self.assertEqual(yoshida['records'][0]['cost_tax_mode'], 'unknown')

    def test_tax_explicit_from_vendors_but_not_retroactive_assumption(self):
        result = normalize_selected_sources(self.specs)
        first = result['private_normalized_docs'][0]['records'][0]
        second = result['private_normalized_docs'][1]['records'][0]
        self.assertEqual(first['cost_tax_mode'], 'excluded')
        # Wako has two different headings that both map to cost_amount.
        # No price can safely be selected from the ambiguous source.
        self.assertEqual(second['cost_tax_mode'], 'unknown')
        self.assertTrue(first['cost_present'])
        self.assertFalse(second['cost_present'])
        self.assertIn('cost_amount',
                      result['public_summary']['ambiguous_field_source_counts'])
        self.assertEqual(result['public_summary']
                         ['ambiguous_field_source_counts']['cost_amount'], 1)

    def test_real_values_absent_from_public_output(self):
        result = normalize_selected_sources(self.specs)
        hit = search_selected_sources(result, field='asin', query=ASIN_Y)
        public = json.dumps([result['public_summary'],
                             hit['public_summary']], ensure_ascii=False)
        for private in (JAN_X, JAN_Y, JAN_Z, ASIN_X, ASIN_Y,
                        '架空マスクA', '600', '650', 'PRIVATE', 'FAKE_INOUE_001',
                        'TEST-M001'):
            self.assertNotIn(private, public)

    def test_records_not_modified_and_no_io(self):
        source = copy.deepcopy(self.specs)
        output = normalize_selected_sources(self.specs)
        self.assertEqual(self.specs, source)
        self.assertEqual(output['public_summary']['source_writes'], 0)
        self.assertEqual(output['public_summary']['api_calls'], 0)

    def test_limits_and_duplicate_source_fail_closed(self):
        with self.assertRaises(ValueError):
            normalize_selected_sources(self.specs * 2)
        with self.assertRaises(ValueError):
            normalize_selected_sources([self.specs[0], self.specs[0]])
        with self.assertRaises(ValueError):
            normalize_selected_sources([{**self.specs[0],
                                        'rows': [[1]] * 201}])
        with self.assertRaises(ValueError):
            normalize_selected_sources([{'document_type': 'quote_response'}])

    def test_query_bounds_and_identifier_fields(self):
        result = normalize_selected_sources(self.specs)
        for field, query in [('jan', '000'), ('asin', 'B0'), ('model', 'A'),
                             ('pretend', 'anything'), ('jan', '１２３４５６７８９０１２３')]:
            with self.subTest(field=field, query=query):
                with self.assertRaises(ValueError):
                    search_selected_sources(result, field=field, query=query)

    def test_five_sources_allowed_no_more(self):
        fifth = copy.deepcopy(self.specs[3])
        fifth['source_file_id'] = 'FAKE_FIFTH_005'
        self.assertEqual(normalize_selected_sources(
            self.specs + [fifth])['public_summary']['source_count'], 5)

    def test_private_rows_still_need_sku_and_price_review(self):
        r = normalize_selected_sources(self.specs)
        for doc in r['private_normalized_docs']:
            for row in doc['records']:
                self.assertEqual(row['decision'], 'needs_confirmation')
        self.assertEqual(r['public_summary']['confirmed_product_matches'], 0)
        self.assertFalse(r['public_summary']['purchase_allowed'])

    def test_two_cost_columns_produce_source_review_not_price(self):
        result = normalize_selected_sources(self.specs)
        wako = result['private_normalized_docs'][1]
        self.assertNotIn('cost_amount', wako['mapped_columns'])
        self.assertTrue(any(
            'AMBIGUOUS_COLUMNS' in warning['codes'] and
            'cost_amount' in warning.get('fields', [])
            for warning in wako['warnings']))
        self.assertEqual(result['public_summary']
                         ['ambiguous_field_source_counts'], {'cost_amount': 1})



    def test_empty_selected_tab_does_not_block_other_suppliers(self):
        examples = sources()
        examples[1]['rows'] = []
        result = normalize_selected_sources(examples)
        self.assertEqual(result['public_summary']['source_status_counts'],
                         {'parsed': 3, 'empty': 1, 'needs_review': 0, 'mapped_review': 0})
        self.assertFalse(result['public_summary']['all_selected_windows_parsed'])
        self.assertEqual(result['private_normalized_docs'][1]['records'], [])
        hit = search_selected_sources(result, field='model', query='TEST-M001')
        self.assertEqual(hit['public_summary']['hits_returned'], 1)
        self.assertEqual(hit['public_summary']['sources_not_searchable'], 1)
        self.assertEqual(hit['public_summary']['sources_with_parsed_headers'], 3)

    def test_unknown_header_requires_review_without_guessing_product(self):
        examples = sources()
        examples[1]['rows'] = [['日付', '概要'], ['2026', '商品らしき何か']]
        result = normalize_selected_sources(examples)
        self.assertEqual(result['public_summary']['source_status_counts']
                         ['needs_review'], 1)
        self.assertEqual(result['private_normalized_docs'][1]['source_status'],
                         'needs_review')
        self.assertEqual(result['private_normalized_docs'][1]['records'], [])
        self.assertFalse(result['public_summary']['purchase_allowed'])

    def test_all_selected_empty_tabs_report_no_results_but_incomplete_coverage(self):
        example = sources()[0]
        example['rows'] = [[]]
        result = normalize_selected_sources([example])
        self.assertEqual(result['public_summary']['record_count'], 0)
        self.assertEqual(result['public_summary']['source_status_counts']['empty'], 1)
        search = search_selected_sources(result, field='model', query='TEST-M001')
        self.assertEqual(search['public_summary']['hits_returned'], 0)
        self.assertEqual(search['public_summary']['sources_not_searchable'], 1)
        self.assertFalse(search['public_summary']['all_supplier_folders_searched'])

    def test_unexpected_parser_errors_are_not_silently_ignored(self):
        examples = sources()
        examples[1]['header_row'] = 99
        with self.assertRaises(ValueError):
            normalize_selected_sources(examples)


if __name__ == '__main__':
    unittest.main()
