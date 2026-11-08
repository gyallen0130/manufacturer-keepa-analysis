"""All cases use synthetic codes and names; no supplier data or network."""
import copy
import json
import unittest

from supplier_docs.identity_matcher import compare_supplier_rows, _gtin


def jan(prefix='000000000001'):
    assert len(prefix) == 12 and prefix.isdigit()
    check = (10 - sum(
        int(d) * (3 if i % 2 else 1)
        for i, d in enumerate(prefix)
    ) % 10) % 10
    return prefix + str(check)


def row(**kwargs):
    return {'jan_string': jan(), 'asin_candidate': 'B0TEST0001',
            'product_name_raw': '架空商品A', **kwargs}


class SupplierIdentityTests(unittest.TestCase):
    def test_gtin_checksum_and_leading_zero(self):
        a = jan()
        self.assertEqual(_gtin(a), a)
        self.assertEqual(_gtin(a[:-1] + str((int(a[-1]) + 1) % 10)), '')
        self.assertEqual(_gtin(int(a)), '')  # no numeric inference
        self.assertEqual(_gtin(' ' + a + ' '), a)
        self.assertEqual(_gtin('000-000-0000001'), '')
        self.assertEqual(_gtin(''), '')

    def test_three_fields_strong_but_not_confirmed(self):
        x = row()
        original = copy.deepcopy(x)
        result = compare_supplier_rows([x], [row()])
        self.assertEqual(result['private_pairs'][0]['status'],
                         'strong_candidate')
        self.assertEqual(result['public_summary']['confirmed_saleable_skus'], 0)
        self.assertEqual(x, original)

    def test_single_asin_only_is_id_candidate(self):
        left = {'asin_candidate': 'A123456789', 'product_name_raw': ''}
        right = {'asin_candidate': 'A123456789', 'product_name_raw': ''}
        result = compare_supplier_rows([left], [right])
        self.assertEqual(result['private_pairs'][0]['status'], 'id_candidate')

    def test_conflicting_asin_overrides_same_jan_and_name(self):
        result = compare_supplier_rows(
            [row()], [row(asin_candidate='B0TEST0002')])
        self.assertEqual(result['private_pairs'][0]['status'], 'conflict')
        self.assertIn('asin_mismatch', result['private_pairs'][0]['evidence_codes'])

    def test_conflicting_jan_overrides_same_asin_and_name(self):
        result = compare_supplier_rows(
            [row()], [row(jan_string=jan('000000000002'))])
        self.assertEqual(result['private_pairs'][0]['status'], 'conflict')

    def test_conflicting_name_overrides_both_ids(self):
        result = compare_supplier_rows(
            [row()], [row(product_name_raw='架空商品B')])
        self.assertEqual(result['private_pairs'][0]['status'], 'conflict')

    def test_name_only_does_not_become_sku(self):
        result = compare_supplier_rows(
            [{'product_name_raw': 'Sample   Model'}],
            [{'product_name_raw': 'sample model'}])
        self.assertEqual(result['private_pairs'][0]['status'], 'name_only')

    def test_asin_list_ambiguity_never_strong(self):
        result = compare_supplier_rows(
            [row(asin_candidate='', asin_candidates=['B0TEST0001', 'B0TEST0002'])],
            [row()])
        self.assertEqual(result['private_pairs'][0]['status'], 'id_candidate')
        self.assertIn('ambiguous_asin', result['private_pairs'][0]['evidence_codes'])

    def test_different_pack_quantity_is_conflict(self):
        result = compare_supplier_rows(
            [row(pack_quantity='1個')],
            [row(pack_quantity='3個')])
        self.assertEqual(result['private_pairs'][0]['status'], 'conflict')
        self.assertIn('pack_mismatch', result['private_pairs'][0]['evidence_codes'])

    def test_supplier_order_multiple_is_not_consumer_pack(self):
        result = compare_supplier_rows(
            [row(order_multiple='6ケース')], [row(order_multiple='1ケース')])
        self.assertEqual(result['private_pairs'][0]['status'],
                         'strong_candidate')

    def test_different_model_and_capacity_conflict(self):
        result = compare_supplier_rows(
            [row(model_number='ABC-1', capacity='250ml')],
            [row(model_number='ABC-2', capacity='500ml')])
        self.assertEqual(result['private_pairs'][0]['status'], 'conflict')
        self.assertIn('model_mismatch', result['private_pairs'][0]['evidence_codes'])
        self.assertIn('size_mismatch', result['private_pairs'][0]['evidence_codes'])

    def test_duplicate_source_rows_downgraded(self):
        result = compare_supplier_rows([row()], [row(), row()])
        self.assertEqual([p['status'] for p in result['private_pairs']],
                         ['id_candidate', 'id_candidate'])
        self.assertTrue(all('multiple_candidate_rows' in p['evidence_codes']
                            for p in result['private_pairs']))

    def test_disjoint_docs_unmatched(self):
        a = row()
        b = row(jan_string=jan('000000000002'),
                asin_candidate='B0TEST0002', product_name_raw='別製品')
        result = compare_supplier_rows([a], [b])
        self.assertEqual(result['private_pairs'], [])
        self.assertEqual(result['public_summary']['unmatched_a_rows'], 1)
        self.assertEqual(result['public_summary']['unmatched_b_rows'], 1)

    def test_reject_oversized_or_invalid_records(self):
        for a, b in [([{}] * 201, []), (None, []), ([None], []),
                     ([{'asin_candidates': 'B0TEST0001'}], [{}])]:
            with self.subTest(a=a is None, length=len(a) if a is not None else 0):
                with self.assertRaises(ValueError):
                    compare_supplier_rows(a, b)

    def test_no_secret_material_in_public_or_private_outputs(self):
        sensitive = row(secret_cost='HIDDEN_CURRENCY_999',
                        source_file_id='PRIVATE_DRIVE_ID_ABC',
                        source_url='PRIVATE_DOC_URL_ABC')
        result = compare_supplier_rows([sensitive], [row()])
        serialized = json.dumps(result, ensure_ascii=False)
        for secret in ('HIDDEN_CURRENCY_999', 'PRIVATE_DRIVE_ID_ABC',
                       'PRIVATE_DOC_URL_ABC', jan(), 'B0TEST0001', '架空商品A'):
            self.assertNotIn(secret, serialized)
        self.assertFalse(result['public_summary']['source_writes'])
        self.assertFalse(result['public_summary']['api_calls'])

    def test_missing_id_does_not_force_exact(self):
        a = row(jan_string='', asin_candidate='B0TEST0001')
        b = row(jan_string='', asin_candidate='B0TEST0001')
        result = compare_supplier_rows([a], [b])
        self.assertEqual(result['private_pairs'][0]['status'], 'id_candidate')

    def test_blank_inputs(self):
        result = compare_supplier_rows([], [])
        self.assertEqual(result['private_pairs'], [])
        self.assertEqual(result['public_summary']['candidate_pairs'], 0)


if __name__ == '__main__':
    unittest.main()
