"""Synthetic-only package-unit safety cases. No account or product data."""
import json
import unittest

from supplier_docs.offer_pack_guard import evaluate_offer_pack_guard, mark_records_from_pack_guard


def manufacturer_quote(**extra):
    return {'items_per_inner_box': 50, 'case_pack': 48, **extra}


def retailer_offer(**extra):
    return {'items_per_inner_box': 50, 'inner_boxes_per_offer': 4,
            'source': 'secondary_listing', **extra}


class OfferPackGuardTests(unittest.TestCase):
    def test_case_pack_is_not_sale_unit(self):
        result = evaluate_offer_pack_guard(manufacturer_quote(), retailer_offer())
        s = result['public_summary']
        self.assertEqual(s['status'], 'needs_quoted_purchase_unit')
        self.assertTrue(s['multipack_hint'])
        self.assertIsNone(result['private_counts']['quoted_total_items'])
        self.assertFalse(s['profit_calculation_allowed'])

    def test_secondary_four_box_listing_vs_verified_one_box_quote(self):
        result = evaluate_offer_pack_guard(
            manufacturer_quote(inner_boxes_per_quoted_unit=1,
                               quote_unit_verified=True),
            retailer_offer())
        self.assertEqual(result['public_summary']['status'],
                         'potential_count_mismatch_secondary')
        self.assertEqual(result['private_counts']['quoted_total_items'], 50)
        self.assertEqual(result['private_counts']['listed_total_items'], 200)

    def test_secondary_two_box_listing_still_not_direct(self):
        result = evaluate_offer_pack_guard(
            manufacturer_quote(inner_boxes_per_quoted_unit=1,
                               quote_unit_verified=True),
            retailer_offer(inner_boxes_per_offer=2))
        self.assertEqual(result['private_counts']['listed_total_items'], 100)
        self.assertEqual(result['public_summary']['status'],
                         'potential_count_mismatch_secondary')

    def test_secondary_matching_counts_not_confirmed(self):
        result = evaluate_offer_pack_guard(
            manufacturer_quote(inner_boxes_per_quoted_unit=4,
                               quote_unit_verified=True),
            retailer_offer())
        self.assertEqual(result['public_summary']['status'],
                         'apparent_count_match_secondary_unverified')
        self.assertFalse(result['public_summary']['amazon_product_identity_confirmed'])

    def test_amazon_direct_count_mismatch_blocks(self):
        result = evaluate_offer_pack_guard(
            manufacturer_quote(inner_boxes_per_quoted_unit=1,
                               quote_unit_verified=True),
            retailer_offer(source='amazon_direct_verified'))
        self.assertEqual(result['public_summary']['status'],
                         'confirmed_count_mismatch')
        self.assertFalse(result['public_summary']['purchase_allowed'])

    def test_amazon_direct_count_match_still_requires_sku(self):
        result = evaluate_offer_pack_guard(
            manufacturer_quote(inner_boxes_per_quoted_unit=4,
                               quote_unit_verified=True),
            retailer_offer(source='amazon_direct_verified'))
        self.assertEqual(result['public_summary']['status'],
                         'count_match_identity_still_unverified')
        self.assertFalse(result['public_summary']['profit_calculation_allowed'])

    def test_quoted_unit_not_verified_no_false_mismatch(self):
        result = evaluate_offer_pack_guard(
            manufacturer_quote(inner_boxes_per_quoted_unit=1,
                               quote_unit_verified=False),
            retailer_offer(source='amazon_direct_verified'))
        self.assertEqual(result['public_summary']['status'],
                         'needs_quoted_purchase_unit')

    def test_missing_listing_quantity_stays_open(self):
        result = evaluate_offer_pack_guard(
            manufacturer_quote(inner_boxes_per_quoted_unit=1,
                               quote_unit_verified=True),
            {'source': 'unverified'})
        self.assertEqual(result['public_summary']['status'],
                         'needs_amazon_offer_unit')
        self.assertFalse(result['public_summary']['multipack_hint'])

    def test_wholesale_case_pack_never_changes_result(self):
        base = evaluate_offer_pack_guard(manufacturer_quote(), retailer_offer())
        changed = evaluate_offer_pack_guard(
            manufacturer_quote(case_pack=12), retailer_offer())
        self.assertEqual(base['public_summary'], changed['public_summary'])

    def test_non_equal_inner_box_counts_warn(self):
        result = evaluate_offer_pack_guard(
            {'items_per_inner_box': 30, 'inner_boxes_per_quoted_unit': 1,
             'quote_unit_verified': True},
            retailer_offer())
        self.assertEqual(result['public_summary']['status'],
                         'potential_count_mismatch_secondary')
        self.assertFalse(result['public_summary']['multipack_hint'])

    def test_reject_non_positive_float_bool_or_huge_counts(self):
        for v in (0, -1, 1.0, True, '4', 10001):
            with self.subTest(v=v):
                with self.assertRaises(ValueError):
                    evaluate_offer_pack_guard(manufacturer_quote(),
                                              retailer_offer(inner_boxes_per_offer=v))

    def test_reject_unknown_listing_source_and_invalid_quote(self):
        for bad in ('amazon_api_trusted', '', None):
            with self.subTest(source=bad):
                with self.assertRaises(ValueError):
                    evaluate_offer_pack_guard(manufacturer_quote(),
                                              retailer_offer(source=bad))
        with self.assertRaises(ValueError):
            evaluate_offer_pack_guard(None, retailer_offer())

    def test_no_product_codes_prices_or_private_identifiers_appear(self):
        q = manufacturer_quote(inner_boxes_per_quoted_unit=1,
                               quote_unit_verified=True,
                               source_file_id='SECRET_DOCUMENT_999',
                               product_name='SECRET_PRODUCT',
                               cost=98765)
        listing = retailer_offer(asin='B0FAKE1234', merchant='SECRET_MERCHANT')
        result = evaluate_offer_pack_guard(q, listing)
        serialized = json.dumps(result, ensure_ascii=False)
        for token in ('SECRET_DOCUMENT_999', 'SECRET_PRODUCT', 'SECRET_MERCHANT',
                      'B0FAKE1234', '98765'):
            self.assertNotIn(token, serialized)
        self.assertEqual(result['public_summary']['source_writes'], 0)
        self.assertEqual(result['public_summary']['api_calls'], 0)


    def test_secondary_pack_discrepancy_downgrades_identity_match(self):
        from supplier_docs.identity_matcher import compare_supplier_rows
        fake = {'jan_string': '0000000000017',
                'asin_candidate': 'B0TEST0001',
                'product_name_raw': 'FAKE ITEM'}
        # No valid JAN needed for this check: the pack-review provenance
        # flag, not the raw barcode, must prevent a strong match.
        guarded = mark_records_from_pack_guard(
            [fake], evaluate_offer_pack_guard(
                manufacturer_quote(inner_boxes_per_quoted_unit=1,
                                   quote_unit_verified=True),
                retailer_offer()))
        self.assertTrue(guarded[0]['offer_pack_review_required'])
        match = compare_supplier_rows([fake], guarded)
        self.assertEqual(match['private_pairs'][0]['status'], 'id_candidate')
        self.assertIn('offer_pack_unit_requires_review',
                      match['private_pairs'][0]['evidence_codes'])

    def test_source_rows_not_mutated_when_flagging_pack_review(self):
        fake = {'asin_candidate': 'B0TEST0001', 'product_name_raw': 'FAKE'}
        original = dict(fake)
        guarded = mark_records_from_pack_guard(
            [fake], evaluate_offer_pack_guard(manufacturer_quote(), retailer_offer()))
        self.assertEqual(fake, original)
        self.assertIsNot(fake, guarded[0])
        self.assertTrue(guarded[0]['offer_pack_review_required'])

    def test_verified_matching_count_does_not_force_false_pack_warning(self):
        fake = {'asin_candidate': 'B0TEST0001'}
        guarded = mark_records_from_pack_guard(
            [fake], evaluate_offer_pack_guard(
                manufacturer_quote(inner_boxes_per_quoted_unit=4,
                                   quote_unit_verified=True),
                retailer_offer(source='amazon_direct_verified')))
        self.assertNotIn('offer_pack_review_required', guarded[0])

    def test_invalid_guard_or_oversized_rows_rejected(self):
        with self.assertRaises(ValueError):
            mark_records_from_pack_guard([{}], {'public_summary': {'status': 'approved'}})
        with self.assertRaises(ValueError):
            mark_records_from_pack_guard([{}] * 201,
                                         evaluate_offer_pack_guard(manufacturer_quote(), retailer_offer()))


if __name__ == '__main__':
    unittest.main()
