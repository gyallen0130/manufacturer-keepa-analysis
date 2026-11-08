"""Integration smoke test: synthetic supplier rows -> parser -> identity matcher.

No Google Drive, Keepa, SP-API, customer/quote data, network or I/O.
"""
import unittest

from supplier_docs.parser import parse_rows
from supplier_docs.identity_matcher import compare_supplier_rows, mark_duplicate_jan_headers


def make_gtin(prefix):
    digits = [int(x) for x in prefix]
    digit = (10 - sum(v * (3 if i % 2 else 1)
                      for i, v in enumerate(digits)) % 10) % 10
    return prefix + str(digit)


def parsed(name='架空商品A', *, jan=None, asin='B0TEST0001'):
    if jan is None:
        jan = make_gtin('000000000001')
    rows = [
        ['メーカー', '商品名', 'JAN', 'ASIN', '卸値'],
        ['架空メーカー', name, jan, asin, '9999'],
    ]
    return parse_rows(rows, document_type='quote_request', include_sensitive=False)


class SupplierIdentityIntegrationTests(unittest.TestCase):
    def test_parser_records_flow_into_matcher(self):
        a, b = parsed(), parsed()
        outcome = compare_supplier_rows(a['records'], b['records'])
        self.assertEqual(outcome['public_summary']['status_counts']['strong_candidate'], 1)
        self.assertEqual(outcome['public_summary']['confirmed_saleable_skus'], 0)
        self.assertEqual(outcome['public_summary']['source_writes'], 0)
        self.assertNotIn('cost_amount', str(outcome))

    def test_parser_derived_conflicting_asin_causes_review(self):
        outcome = compare_supplier_rows(
            parsed()['records'],
            parsed(asin='B0TEST0002')['records'],
        )
        self.assertEqual(outcome['public_summary']['status_counts']['conflict'], 1)

    def test_parser_does_not_create_purchase_decision(self):
        result = parsed()
        self.assertTrue(all(r['decision'] == 'needs_confirmation' for r in result['records']))
        outcome = compare_supplier_rows(result['records'], parsed()['records'])
        self.assertEqual(outcome['public_summary']['decision'], 'human_review_required')


    def test_parser_rows_with_unresolved_duplicate_jan_provenance_are_downgraded(self):
        a = parsed()['records']
        b = parsed()['records']
        # The reader saw multiple 'JAN' headers and must preserve that fact
        # in the private record until their business meaning is verified.
        for record in b:
            record['jan_source_ambiguous'] = True
        outcome = compare_supplier_rows(a, b)
        self.assertEqual(outcome['public_summary']['status_counts']['strong_candidate'], 0)
        self.assertEqual(outcome['public_summary']['status_counts']['id_candidate'], 1)
        self.assertIn('jan_columns_require_review',
                      outcome['private_pairs'][0]['evidence_codes'])


    def test_parser_then_header_provenance_guard(self):
        a = parsed()['records']
        b = parsed()['records']
        copied = mark_duplicate_jan_headers(
            b, ['メーカー', '商品名', 'JAN', 'ASIN', 'JAN'])
        result = compare_supplier_rows(a, copied)
        self.assertEqual(result['public_summary']['status_counts']['id_candidate'], 1)
        self.assertEqual(result['public_summary']['status_counts']['strong_candidate'], 0)


if __name__ == '__main__':
    unittest.main()
