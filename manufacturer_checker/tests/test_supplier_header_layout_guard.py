"""Synthetic structural examples; NO real supplier prices, JANs or products."""
import json
import unittest

from supplier_docs.header_layout_guard import inspect_header_layout
from supplier_docs.multi_source_readonly import normalize_selected_sources


def lead_off_tiered():
    rows = [[] for _ in range(15)]
    rows[11] = ['', '商品ｺｰﾄﾞ']
    rows[12] = ['', '', '', '', '商品名・POSｺｰﾄﾞ・ITFｺｰﾄﾞ']
    rows[13] = ['', '', '', '', '', '', '', '入数', '', '', '価格']
    rows[14] = ['', '', '', '', '', '', '', '', '', '価格']
    return rows + [['架空商品', '架空番号', 'その他']]


class SupplierHeaderLayoutTests(unittest.TestCase):
    def test_itou_header_on_third_row_duplicate_jan(self):
        rows = [[], [], ['商品名', 'JAN', 'ASIN', 'JAN', 'ケース入数', '単価']]
        result = inspect_header_layout(rows)
        self.assertEqual(result['status'], 'single_row')
        self.assertEqual(result['header_row'], 3)
        self.assertIn('duplicate_jan_heading', result['warnings'])

    def test_inoue_header_on_first_row(self):
        rows = [['', '品番', 'JAN', '商品名', '上代(税抜）',
                 '発注単位', '下代(税抜）']]
        result = inspect_header_layout(rows)
        self.assertEqual(result['status'], 'single_row')
        self.assertEqual(result['header_row'], 1)
        self.assertNotIn('duplicate_jan_heading', result['warnings'])

    def test_blacks_sixteen_row_preamble_two_price_hints(self):
        rows = [[] for _ in range(15)]
        rows[15] = ['商品名', '卸値税抜', '卸値税込', '定価',
                    '概算利益', '利益率', '', 'JANコード']
        result = inspect_header_layout(rows)
        self.assertEqual(result['status'], 'single_row')
        self.assertEqual(result['header_row'], 16)
        self.assertIn('multiple_price_hints', result['warnings'])

    def test_lead_off_tiered_rows_are_not_merged_into_fake_price(self):
        result = inspect_header_layout(lead_off_tiered())
        self.assertEqual(result['status'], 'multi_row_needs_review')
        self.assertIsNone(result['header_row'])
        self.assertEqual(result['header_span'], [12, 14])
        self.assertEqual(result['prices_returned'], 0)

    def test_tiered_source_does_not_stop_other_supplier(self):
        source = [
            {'source_file_id': 'FAKE_HEADER_VENDOR_A_0001',
             'source_sheet': 'Sheet1', 'document_type': 'quote_response',
             'rows': lead_off_tiered()},
            {'source_file_id': 'FAKE_HEADER_VENDOR_B_0002',
             'source_sheet': '見積もり', 'document_type': 'quote_response',
             'rows': [['商品名', 'JAN', '品番'],
                      ['架空テープ', '0000000000017', 'MODEL-123']]},
        ]
        outcome = normalize_selected_sources(source)
        s = outcome['public_summary']
        self.assertEqual(s['source_status_counts']['needs_review'], 1)
        self.assertEqual(s['source_status_counts']['parsed'], 1)
        self.assertEqual(s['header_layout_counts']['multi_row_needs_review'], 1)
        self.assertEqual(outcome['private_normalized_docs'][0]['records'], [])
        self.assertFalse(s['profit_calculation_allowed'])

    def test_no_reliable_header_stays_unverified(self):
        data = inspect_header_layout([['日付', '分類'], ['架空商品の明細']])
        self.assertEqual(data['status'], 'no_reliable_header')

    def test_empty_windows(self):
        for rows in ([], [[], [None, '']]):
            self.assertEqual(inspect_header_layout(rows)['status'], 'empty')

    def test_non_text_jan_cells_do_not_become_headings(self):
        rows = [['商品名', 1234567890123, 'ASIN']]
        s = inspect_header_layout(rows)
        self.assertEqual(s['status'], 'single_row')
        self.assertNotIn('jan', s['heading_categories'])

    def test_privacy_and_no_source_writes(self):
        raw = [['商品名', 'JAN', '単価'],
               ['VERY_PRIVATE_ITEM_314', '8888888888888', 987654]]
        result = inspect_header_layout(raw)
        summary = json.dumps(result, ensure_ascii=False)
        for token in ('VERY_PRIVATE_ITEM_314', '8888888888888', '987654'):
            self.assertNotIn(token, summary)
        self.assertEqual(result['source_writes'], 0)
        self.assertEqual(result['product_values_returned'], 0)

    def test_reject_oversize_or_bad_rows(self):
        for data in ([[]] * 41, [[None] * 16], ['str'], 'not a matrix'):
            with self.subTest(data_type=type(data).__name__):
                with self.assertRaises(ValueError):
                    inspect_header_layout(data)


if __name__ == '__main__':
    unittest.main()
