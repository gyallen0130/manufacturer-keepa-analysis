"""Synthetic only: no Google credentials, live Drive data or vendor prices."""
import copy
import json
import unittest

from supplier_docs.connector_sheet_snapshot import (
    SCHEMA_VERSION, MODE, normalize_selected_connector_snapshots)
from supplier_docs.mixed_source_readonly import combine_selected_source_results
from supplier_docs.multi_source_readonly import normalize_selected_sources

JAN = '0000000000017'
ASIN = 'B0TEST0001'
SOURCE_ID = 'FAKE_CONNECTOR_SHEET_001'


def manifest(method='native_export_xlsx'):
    return {
        'schema_version': SCHEMA_VERSION, 'mode': MODE,
        'sources': [{
            'spreadsheet_id': SOURCE_ID,
            'sheet_name': '架空シート', 'document_type': 'quote_request',
            'snapshot_method': method,
            'rows': [['商品名', 'JAN', 'ASIN'],
                     ['PRIVATE_FAKE_PRODUCT', JAN, ASIN]],
        }],
    }


def fake_excel_normalized():
    specs = [{
        'source_file_id': 'FAKE_LOCAL_EXCEL_001',
        'source_sheet': '見積',
        'document_type': 'quote_request',
        'rows': [['商品名', 'JAN', 'ASIN'],
                 ['PRIVATE_EXCEL_PRODUCT', JAN, 'B0TEST0002']],
    }]
    result = normalize_selected_sources(specs)
    result['public_summary'].update({
        'schema_version': 'manual-local-excel-v1',
        'mode': 'manual_local_excel_readonly',
        'api_calls': 0,
    })
    return result


class ConnectorSnapshotTests(unittest.TestCase):
    def test_native_export_snapshot_uses_common_parser(self):
        result = normalize_selected_connector_snapshots(manifest=manifest())
        summary = result['public_summary']
        self.assertEqual(summary['source_count'], 1)
        self.assertEqual(summary['record_count'], 1)
        self.assertEqual(summary['source_status_counts']['parsed'], 1)
        self.assertEqual(summary['api_calls'], 0)
        self.assertEqual(summary['connector_reads_performed_by_this_function'], 0)
        self.assertFalse(summary['connector_auth_verified_by_this_function'])
        self.assertTrue(summary['xlsx_export_type_fidelity_requires_review'])
        self.assertFalse(summary['profit_calculation_allowed'])
        self.assertFalse(summary['purchase_allowed'])

    def test_native_snapshot_plus_excel_combines_with_real_mixed_module(self):
        sheets = normalize_selected_connector_snapshots(manifest=manifest())
        merged = combine_selected_source_results(
            [fake_excel_normalized(), sheets],
            search={'field': 'jan', 'query': JAN})
        self.assertEqual(merged['public_summary']['source_count'], 2)
        self.assertEqual(merged['public_summary']['source_kind_counts'],
                         {'excel': 1, 'sheets': 1})
        self.assertEqual(merged['public_summary']['record_count'], 2)
        self.assertEqual(merged['public_search_summary']['hits_returned'], 2)
        self.assertEqual([x['source_index'] for x in merged['private_hits']], [0, 1])
        self.assertFalse(merged['public_search_summary']['product_identity_confirmed'])

    def test_exact_asin_lookup_returns_original_physical_row(self):
        result = normalize_selected_connector_snapshots(
            manifest=manifest(),
            search={'field': 'asin', 'query': ASIN})
        self.assertEqual(result['public_search_summary']['hits_returned'], 1)
        self.assertEqual(result['private_hits'][0]['source_row'], 2)
        self.assertEqual(result['private_hits'][0]['source_index'], 0)
        self.assertEqual(result['private_normalized_docs'][0]['source_file_id'], SOURCE_ID)

    def test_connector_formula_values_method_keeps_numeric_types_and_formulas(self):
        conf = manifest('connector_formula_values')
        conf['sources'][0]['rows'][1][1] = 100000000017
        conf['sources'][0]['rows'][1][2] = '=1+1'
        result = normalize_selected_connector_snapshots(manifest=conf)
        public = result['public_summary']
        self.assertFalse(public['xlsx_export_type_fidelity_requires_review'])
        self.assertEqual(public['formula_cells_present'], 1)
        warnings = result['private_normalized_docs'][0]['warnings']
        self.assertIn('JAN_NUMERIC_CELL',
                      [code for w in warnings for code in w['codes']])

    def test_no_private_values_in_public_result(self):
        result = normalize_selected_connector_snapshots(
            manifest=manifest(), search={'field': 'jan', 'query': JAN})
        public = json.dumps([result['public_summary'],
                             result['public_search_summary']], ensure_ascii=False)
        for token in (JAN, ASIN, SOURCE_ID, 'PRIVATE_FAKE_PRODUCT', '架空シート'):
            self.assertNotIn(token, public)

    def test_does_not_modify_snapshot_input(self):
        original = manifest()
        copied = copy.deepcopy(original)
        normalize_selected_connector_snapshots(manifest=original)
        self.assertEqual(original, copied)

    def test_duplicate_or_unbounded_sources_are_rejected(self):
        for n in (2, 6):
            conf = manifest()
            conf['sources'] = [copy.deepcopy(conf['sources'][0]) for _ in range(n)]
            with self.subTest(n=n), self.assertRaises(ValueError):
                normalize_selected_connector_snapshots(manifest=conf)
        conf = manifest()
        conf['sources'][0]['rows'] = [[] for _ in range(41)]
        with self.assertRaises(ValueError):
            normalize_selected_connector_snapshots(manifest=conf)
        conf = manifest()
        conf['sources'][0]['rows'] = [[None] * 16]
        with self.assertRaises(ValueError):
            normalize_selected_connector_snapshots(manifest=conf)

    def test_unknown_source_and_unsafe_values_rejected(self):
        for field, bad in [
            ('snapshot_method', 'imaginary-authenticated'),
            ('spreadsheet_id', '../fake'),
            ('sheet_name', 'bad!tab'),
            ('document_type', ['catalog']),
            ('snapshot_method', []),
            ('rows', [['商品名'], [{'secret':'value'}]]),
            ('rows', [['商品名'], ['x' * 4001]]),
        ]:
            conf = manifest()
            conf['sources'][0][field] = bad
            with self.subTest(field=field, bad_type=type(bad).__name__):
                with self.assertRaises(ValueError):
                    normalize_selected_connector_snapshots(manifest=conf)

    def test_unknown_key_and_invalid_queries_rejected(self):
        conf = manifest()
        conf['sources'][0]['extra_secret'] = 'value'
        with self.assertRaises(ValueError):
            normalize_selected_connector_snapshots(manifest=conf)
        for query in ({'field': 'jan', 'query': 'x'},
                      {'field': 'wrong', 'query': 'test'},
                      {'field': 'asin', 'query': 12}):
            with self.assertRaises(ValueError):
                normalize_selected_connector_snapshots(
                    manifest=manifest(), search=query)

    def test_empty_or_unknown_header_does_not_claim_search_complete(self):
        conf = manifest()
        conf['sources'][0]['rows'] = []
        empty = normalize_selected_connector_snapshots(manifest=conf)
        self.assertEqual(empty['public_summary']['source_status_counts']['empty'], 1)
        self.assertFalse(empty['public_summary']['all_selected_windows_parsed'])
        conf['sources'][0]['rows'] = [['日付','コメント'], ['x', 'y']]
        unknown = normalize_selected_connector_snapshots(manifest=conf)
        self.assertEqual(unknown['public_summary']
                         ['source_status_counts']['needs_review'], 1)

    def test_conflicting_mappings_rejected(self):
        conf = manifest()
        conf['sources'][0]['header_row'] = 1
        conf['sources'][0]['tiered_mapping'] = {'version':'fake'}
        with self.assertRaises(ValueError):
            normalize_selected_connector_snapshots(manifest=conf)


    def test_native_export_never_confirms_price_or_order_unit(self):
        conf = manifest('native_export_xlsx')
        conf['sources'][0]['document_type'] = 'quote_response'
        conf['sources'][0]['rows'] = [
            ['商品名', 'JAN', '下代（税抜）', '発注単位'],
            ['架空の商品', JAN, 500, '1箱'],
        ]
        result = normalize_selected_connector_snapshots(manifest=conf)
        rec = result['private_normalized_docs'][0]['records'][0]
        self.assertEqual(result['public_summary']['native_export_cost_flags_suppressed'], 1)
        self.assertEqual(result['public_summary']['records_with_cost_field'], 0)
        self.assertFalse(rec['cost_present'])
        self.assertEqual(rec['cost_tax_mode'], 'unknown')
        self.assertEqual(rec['order_multiple'], '')
        self.assertEqual(rec['decision'], 'needs_confirmation')

    def test_native_live_formula_values_are_not_export_suppressed(self):
        conf = manifest('connector_formula_values')
        conf['sources'][0]['document_type'] = 'quote_response'
        conf['sources'][0]['rows'] = [
            ['商品名', 'JAN', '下代（税抜）'],
            ['架空の商品', JAN, 500],
        ]
        result = normalize_selected_connector_snapshots(manifest=conf)
        rec = result['private_normalized_docs'][0]['records'][0]
        self.assertEqual(result['public_summary']['native_export_cost_flags_suppressed'], 0)
        self.assertTrue(rec['cost_present'])
        # Even direct FORMULA values alone do NOT authorize profit or ordering.
        self.assertFalse(result['public_summary']['profit_calculation_allowed'])



if __name__ == '__main__':
    unittest.main()
