"""Synthetic-only coverage: ambiguous quote JAN columns are never resolved silently."""
import copy
import json
import unittest

from supplier_docs.quote_jan_audit import (
    attach_jan_audit_to_records, inspect_explicit_jan_columns,
)
from supplier_docs.identity_matcher import compare_supplier_rows


def fake_rows():
    return [
        [], [], ['商品名', 'JAN', 'ASIN', 'JAN', 'ケース入数', '単価'],
        ['架空商品A', 4900000000001, 'B0TEST0001', 4900000000001, 12, 100],
        ['架空商品B', 4900000000002, 'B0TEST0002', 4900000000009, 24, 200],
        ['架空商品C', 4900000000003, 'B0TEST0003', 4900000000003, 10, 300],
        ['架空商品D', 4900000000004, 'B0TEST0004', 4900000000008, 30, 400],
        ['架空商品E', 4900000000005, 'B0TEST0005', 4900000000005, 12, 500],
        ['架空商品F', 4900000000006, 'B0TEST0006', '廃番', '廃番', '廃番'],
    ]


def audit(rows=None):
    return inspect_explicit_jan_columns(
        rows if rows is not None else fake_rows(),
        header_row_index=2, request_jan_column=1, reply_jan_column=3,
        reply_note_columns=(3, 4, 5),
    )


class QuoteJanAuditTests(unittest.TestCase):
    def test_quote_response_pattern_safe_summary(self):
        result = audit()
        self.assertEqual(result['public_summary']['status_counts'], {
            'same_as_displayed': 3,
            'different_as_displayed': 2,
            'historical_unavailable_note': 1,
            'missing_or_unreadable': 0,
        })
        self.assertEqual(result['public_summary']['confirmed_saleable_skus'], 0)
        self.assertFalse(result['public_summary']['jan_header_roles_verified'])
        self.assertTrue(result['public_summary']['requires_human_review'])

    def test_physical_row_positions_are_one_based(self):
        self.assertEqual([x['physical_row'] for x in audit()['private_row_evidence']],
                         [4, 5, 6, 7, 8, 9])

    def test_no_values_or_supplier_names_in_output(self):
        text = json.dumps(audit(), ensure_ascii=False)
        for forbidden in ('架空商品', '4900000000001', '4900000000009',
                          'B0TEST0001', '廃番', '100'):
            self.assertNotIn(forbidden, text)
        self.assertEqual(audit()['public_summary']['source_writes'], 0)

    def test_input_not_mutated(self):
        rows = fake_rows()
        original = copy.deepcopy(rows)
        audit(rows)
        self.assertEqual(rows, original)

    def test_numeric_jan_cannot_be_trusted_as_gtin(self):
        result = audit()
        self.assertTrue(all(
            'numeric_jan_needs_original_format_review' in item['review_codes']
            for item in result['private_row_evidence']))

    def test_string_jan_leading_zero_compared_exactly(self):
        rows = [[], ['商品名', 'JAN', 'ASIN', 'JAN'],
                ['架空品', '0000000000012', 'B0TEST0001', '0000000000012']]
        res = inspect_explicit_jan_columns(
            rows, header_row_index=1, request_jan_column=1, reply_jan_column=3)
        self.assertEqual(res['public_summary']['status_counts']['same_as_displayed'], 1)

    def test_invalid_columns_fail_closed(self):
        for left,right in [(1, 1), (1, 20), (-1, 3)]:
            with self.subTest(left=left,right=right):
                with self.assertRaises(ValueError):
                    inspect_explicit_jan_columns(
                        fake_rows(), header_row_index=2,
                        request_jan_column=left, reply_jan_column=right)
        with self.assertRaises(ValueError):
            audit([[], [], ['商品名', 'JAN', 'ASIN', 'JAN-備考']])

    def test_large_table_rejected(self):
        with self.assertRaises(ValueError):
            audit(fake_rows() * 29)

    def test_record_annotation_keeps_original(self):
        records = [{'jan_string': '0000000000012',
                    'asin_candidate': 'B0TEST0001',
                    'product_name_raw': '架空商品A'}]
        before = copy.deepcopy(records)
        annotated = attach_jan_audit_to_records(
            records, physical_row_numbers=[4], audit=audit())
        self.assertEqual(records, before)
        self.assertTrue(annotated[0]['jan_source_ambiguous'])
        self.assertEqual(annotated[0]['supplier_quote_review_codes'],
                         ['numeric_jan_needs_original_format_review', 'same_as_displayed'])
        match = compare_supplier_rows(records, annotated)
        self.assertEqual(match['public_summary']['status_counts']['strong_candidate'], 0)
        self.assertEqual(match['public_summary']['status_counts']['id_candidate'], 1)

    def test_missing_duplicate_and_mismatched_rows_rejected(self):
        a = [{'product_name_raw': 'X'}]
        for nums in ([11], [4, 4], [], ['4']):
            with self.subTest(nums=nums):
                with self.assertRaises(ValueError):
                    attach_jan_audit_to_records(
                        a, physical_row_numbers=nums, audit=audit())

    def test_unavailable_is_historical_marker_not_current_inventory(self):
        res = audit()
        last = res['private_row_evidence'][-1]
        self.assertEqual(last['status'], 'historical_unavailable_note')
        self.assertFalse(res['public_summary']['jan_header_roles_verified'])
        self.assertEqual(res['public_summary']['confirmed_saleable_skus'], 0)

    def test_no_marker_by_substring_in_product_name(self):
        rows = [[], ['商品名', 'JAN', 'JAN', '備考'],
                ['廃番について', 4900000000001, 4900000000001, ''] ]
        res = inspect_explicit_jan_columns(
            rows, header_row_index=1, request_jan_column=1,
            reply_jan_column=2, reply_note_columns=(2, 3))
        self.assertEqual(res['public_summary']['status_counts']['same_as_displayed'], 1)


if __name__ == '__main__':
    unittest.main()
