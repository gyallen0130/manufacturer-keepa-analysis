"""Synthetic POS and ITF row-label fixtures; no real vendor items/IDs."""
import copy
import json
import unittest

from supplier_docs.multi_source_readonly import (
    normalize_selected_sources, search_selected_sources)
from supplier_docs.row_labeled_candidates import (
    VERSION, extract_row_labeled_candidates, valid_gtin_digits,
    validate_row_label_mapping)

POS = '0000000000017'
ITF = '10000000000007'
ASIN = 'B0TEST0001'


def rows():
    data = [[] for _ in range(20)]
    data[11] = ['', '商品コード']
    data[12] = ['', '', '', '', '商品名・POSコード・ITFコード']
    data[13] = ['', '', '', '', '', '', '', '入数', '', '', '価格']
    data[14] = ['', '', '', '', '', '', '', '', '', '', '価格']
    data[16] = ['', '', '', 'POSｺｰﾄﾞ：', POS, 'ITFｺｰﾄﾞ：', ITF]
    data[18] = ['', '', '', 'POSコード:', '000000000017',
                'ITFコード:', '-']
    data[19] = ['', '', '', 'POSコード:', 1234567890123,
                'ITFコード:', '=1+1']
    return data


def mapping():
    return {
        'version': VERSION, 'data_start_row': 16,
        'fields': {
            'pos_candidate': {'label_column': 4, 'value_column': 5},
            'itf_candidate': {'label_column': 6, 'value_column': 7},
        },
    }


def source():
    return {'source_file_id': 'FAKE_ROW_LABEL_VENDOR_001',
            'source_sheet': '架空階層価格表', 'document_type': 'catalog',
            'rows': rows(), 'row_labeled_mapping': mapping()}


class RowLabeledCandidatesTests(unittest.TestCase):
    def test_valid_gtin12_13_and_itf14_without_jan_assertion(self):
        self.assertTrue(valid_gtin_digits(POS, kind='pos_candidate'))
        self.assertTrue(valid_gtin_digits('000000000017', kind='pos_candidate'))
        self.assertTrue(valid_gtin_digits(ITF, kind='itf_candidate'))
        self.assertFalse(valid_gtin_digits(POS, kind='itf_candidate'))

    def test_labeled_rows_become_review_only_not_jan(self):
        result = normalize_selected_sources([source()])
        s = result['public_summary']
        self.assertEqual(s['source_status_counts']['labeled_review'], 1)
        self.assertFalse(s['all_selected_windows_parsed'])
        self.assertEqual(s['records_with_pos_candidate'], 2)
        self.assertEqual(s['records_with_itf_candidate'], 1)
        self.assertEqual(s['records_with_jan'], 0)
        self.assertFalse(s['profit_calculation_allowed'])
        self.assertFalse(s['purchase_allowed'])
        d = result['private_normalized_docs'][0]
        self.assertEqual([r['source_row'] for r in d['records']], [17, 19])
        self.assertEqual(d['records'][0]['pos_candidate'], POS)
        self.assertEqual(d['records'][0]['itf_candidate'], ITF)
        self.assertEqual(d['records'][0]['jan_string'], '')
        self.assertTrue(all(r['decision'] == 'needs_confirmation'
                            and r['product_name_raw'] == ''
                            and not r['cost_present']
                            for r in d['records']))

    def test_pos_exact_lookup_and_jan_never_cross_equated(self):
        result = normalize_selected_sources([source()])
        pos = search_selected_sources(result, field='pos', query=POS)
        jan = search_selected_sources(result, field='jan', query=POS)
        self.assertEqual(pos['public_summary']['hits_returned'], 1)
        self.assertEqual(pos['private_hits'][0]['source_row'], 17)
        self.assertEqual(jan['public_summary']['hits_returned'], 0)
        self.assertEqual(jan['public_summary']['sources_without_field_coverage'], 1)
        self.assertFalse(pos['public_summary']['product_identity_confirmed'])

    def test_itf_exact_lookup(self):
        result = normalize_selected_sources([source()])
        hit = search_selected_sources(result, field='itf', query=ITF)
        self.assertEqual(hit['public_summary']['hits_returned'], 1)
        self.assertEqual(hit['public_summary']['sources_with_row_labeled_candidates'], 1)

    def test_numeric_identifier_must_not_restore_possible_leading_zero(self):
        result = normalize_selected_sources([source()])
        warn = result['private_normalized_docs'][0]['warnings']
        self.assertIn('NUMERIC_BARCODE_NOT_TRUSTED',
                      [code for w in warn for code in w['codes']])
        self.assertEqual(result['public_summary']['records_with_pos_candidate'], 2)

    def test_formula_and_empty_labels_never_become_identifiers(self):
        result = normalize_selected_sources([source()])
        codes = [code for w in result['private_normalized_docs'][0]['warnings']
                 for code in w['codes']]
        self.assertIn('BARCODE_FORMULA_NOT_TRUSTED', codes)
        self.assertIn('LABELED_IDENTIFIER_EMPTY', codes)
        self.assertEqual(result['public_summary']['records_with_itf_candidate'], 1)

    def test_wrong_label_rejected_without_guessing(self):
        s = source()
        s['rows'][16][3] = 'POS(推測)'
        s['rows'][16][5] = 'ITF(推測)'
        result = normalize_selected_sources([s])
        self.assertEqual(result['public_summary']['records_with_pos_candidate'], 1)
        self.assertEqual(result['public_summary']['records_with_itf_candidate'], 0)

    def test_invalid_checksum_and_numeric_text_not_promoted(self):
        s = source()
        s['rows'][16][4] = '0000000000018'
        s['rows'][16][6] = '10000000000008'
        result = normalize_selected_sources([s])
        self.assertEqual(result['public_summary']['records_with_itf_candidate'], 0)
        self.assertEqual(result['public_summary']['records_with_pos_candidate'], 1)
        warnings = result['private_normalized_docs'][0]['warnings']
        self.assertIn('BARCODE_FORMAT_OR_CHECKSUM_UNVERIFIED',
                      [code for w in warnings for code in w['codes']])

    def test_invalid_schema_rejected(self):
        variants = []
        wrong = mapping()
        wrong['fields']['cost_amount'] = {'label_column': 8, 'value_column': 9}
        variants.append(wrong)
        wrong = mapping()
        wrong['fields']['pos_candidate']['label_column'] = True
        variants.append(wrong)
        wrong = mapping()
        wrong['fields']['itf_candidate'] = {'label_column': 5, 'value_column': 6}
        variants.append(wrong)
        wrong = mapping()
        wrong['data_start_row'] = 41
        variants.append(wrong)
        for invalid in variants:
            with self.subTest(bad=str(invalid)[:35]), self.assertRaises(ValueError):
                validate_row_label_mapping(invalid)

    def test_cannot_combine_header_mapping_with_row_label_mapping(self):
        s = source()
        s['tiered_mapping'] = {'version': 'fake'}
        with self.assertRaises(ValueError):
            normalize_selected_sources([s])
        s = source()
        s['header_row'] = 1
        with self.assertRaises(ValueError):
            normalize_selected_sources([s])

    def test_single_row_source_refuses_row_label_override(self):
        s = source()
        s['rows'] = [['商品名', 'JAN', '単価'], ['架空商品', POS, 120]]
        with self.assertRaises(ValueError):
            normalize_selected_sources([s])

    def test_missing_labels_stays_unparsed_not_product_absent(self):
        s = source()
        s['rows'][16] = ['架空のみ', '', '']
        s['rows'][18] = ['', '', '']
        s['rows'][19] = ['', '', '']
        result = normalize_selected_sources([s])
        self.assertEqual(result['public_summary']['source_status_counts']['needs_review'], 1)
        self.assertEqual(result['public_summary']['record_count'], 0)

    def test_mixed_ordinary_and_row_labeled_search_respects_fields(self):
        original = {'source_file_id': 'FAKE_STANDARD_VENDOR_002',
                    'source_sheet': '見積', 'document_type': 'quote_request',
                    'rows': [['商品名', 'JAN', 'ASIN'], ['架空商品', POS, ASIN]]}
        result = normalize_selected_sources([source(), original])
        self.assertEqual(search_selected_sources(
            result, field='jan', query=POS)['public_summary']['hits_returned'], 1)
        self.assertEqual(search_selected_sources(
            result, field='pos', query=POS)['public_summary']['hits_returned'], 1)
        self.assertFalse(result['public_summary']['all_selected_windows_parsed'])

    def test_source_not_modified_public_aggregates_do_not_leak(self):
        s = source()
        initial = copy.deepcopy(s)
        result = normalize_selected_sources([s])
        self.assertEqual(s, initial)
        hit = search_selected_sources(result, field='pos', query=POS)
        public = json.dumps([result['public_summary'],
                             hit['public_summary']], ensure_ascii=False)
        for private in (POS, ITF, 'FAKE_ROW_LABEL_VENDOR_001',
                        '10000000000007', '架空階層価格表'):
            self.assertNotIn(private, public)
        self.assertEqual(result['public_summary']['source_writes'], 0)


if __name__ == '__main__':
    unittest.main()
