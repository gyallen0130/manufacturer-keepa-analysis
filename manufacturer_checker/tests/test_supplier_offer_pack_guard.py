"""Synthetic-only package-unit safety cases. No account or product data."""
import json
import unittest

from supplier_docs.offer_pack_guard import (evaluate_offer_pack_guard, mark_records_from_pack_guard, quote_unit_from_document_evidence)


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
        for bad in ('amazon_api_trusted', '', None, [], {}, True):
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


    def test_historical_other_email_case_pack_not_quote_unit_proof(self):
        evidence = {'scope': 'other_promotion',
                    'kind': 'case_pack_and_price_only',
                    'case_pack': 50, 'price': 275,
                    'source_id': 'PRIVATE_GMAIL_MESSAGE'}
        result = quote_unit_from_document_evidence(evidence)
        self.assertEqual(result['public_summary']['status'],
                         'related_promotion_cannot_verify_quote_unit')
        self.assertFalse(result['public_summary']['quote_unit_verified'])
        self.assertIsNone(result['private_guard_quote']['inner_boxes_per_quoted_unit'])
        self.assertNotIn('PRIVATE_GMAIL_MESSAGE', json.dumps(result))
        self.assertNotIn('275', json.dumps(result))

    def test_same_quote_case_pack_and_price_is_still_not_explicit_unit(self):
        evidence = quote_unit_from_document_evidence({
            'scope': 'target_quote', 'kind': 'case_pack_and_price_only',
            'retail_boxes_per_quoted_price': 1})
        self.assertFalse(evidence['public_summary']['quote_unit_verified'])
        self.assertIsNone(evidence['private_guard_quote']['inner_boxes_per_quoted_unit'])

    def test_explicit_unit_only_on_target_quote_may_propagate(self):
        evidence = quote_unit_from_document_evidence({
            'scope': 'target_quote',
            'kind': 'explicit_per_retail_box',
            'retail_boxes_per_quoted_price': 1})
        self.assertTrue(evidence['public_summary']['quote_unit_verified'])
        self.assertEqual(evidence['private_guard_quote']['inner_boxes_per_quoted_unit'], 1)
        # Original manufacturer retail box contents must be confirmed
        # independently before this non-profit pack guard can compare.
        quote = {'items_per_inner_box': 50,
                 **evidence['private_guard_quote']}
        pack = evaluate_offer_pack_guard(quote, retailer_offer())
        self.assertEqual(pack['public_summary']['status'],
                         'potential_count_mismatch_secondary')
        self.assertFalse(pack['public_summary']['profit_calculation_allowed'])

    def test_explicit_other_promotion_is_not_current_quote_proof(self):
        evidence = quote_unit_from_document_evidence({
            'scope': 'other_promotion',
            'kind': 'explicit_per_retail_box',
            'retail_boxes_per_quoted_price': 1})
        self.assertFalse(evidence['public_summary']['quote_unit_verified'])

    def test_unverified_source_does_not_fabricate_box_counts(self):
        evidence = quote_unit_from_document_evidence({})
        self.assertEqual(evidence['public_summary']['status'],
                         'quote_price_unit_not_verified')
        guard = evaluate_offer_pack_guard(
            {'items_per_inner_box': 50, **evidence['private_guard_quote']},
            retailer_offer())
        self.assertEqual(guard['public_summary']['status'],
                         'needs_quoted_purchase_unit')

    def test_reject_invalid_quote_source_and_box_units(self):
        for bad in (True, [], {}, None, 'imaginary'):
            with self.subTest(value=repr(bad)):
                with self.assertRaises(ValueError):
                    quote_unit_from_document_evidence({
                        'scope': bad, 'kind': 'case_pack_and_price_only'})
        for count in (True, 0, 1.5, '1', -1, 10001):
            with self.subTest(count=repr(count)):
                with self.assertRaises(ValueError):
                    quote_unit_from_document_evidence({
                        'scope': 'target_quote',
                        'kind': 'explicit_per_retail_box',
                        'retail_boxes_per_quoted_price': count})


if __name__ == '__main__':
    unittest.main()
