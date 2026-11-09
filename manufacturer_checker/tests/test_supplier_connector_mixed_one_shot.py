"""Synthetic-only connector snapshot + local Excel combined search tests."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from openpyxl import Workbook
from supplier_docs.connector_mixed_one_shot import inspect_private_connector_mixed
from supplier_docs.connector_sheet_snapshot import (
    SCHEMA_VERSION as SNAP_VERSION, MODE as SNAP_MODE,
)
from supplier_docs.local_excel_bridge import (
    SCHEMA_VERSION as XLS_VERSION, MODE as XLS_MODE,
)

FAKE_JAN = '0000000000017'
FAKE_ASIN = 'B0TEST0001'
FAKE_ID = 'SYNTHETIC_SHEET_ID_001'


class ConnectorMixedOneShotTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        book = Workbook()
        tab = book.active
        tab.title = 'FakeQuote'
        tab.append(['商品名', 'JAN', 'ASIN'])
        tab.append(['架空Excel商品', FAKE_JAN, FAKE_ASIN])
        book.save(self.root / 'fake.xlsx')
        book.close()
        self.original_bytes = (self.root / 'fake.xlsx').read_bytes()

        self.excel = {
            'schema_version': XLS_VERSION, 'mode': XLS_MODE,
            'targets': [{'relative_path': 'fake.xlsx',
                         'sheet_name': 'FakeQuote',
                         'document_type': 'quote_request'}],
        }
        self.sheets = {
            'schema_version': SNAP_VERSION, 'mode': SNAP_MODE,
            'sources': [{
                'spreadsheet_id': FAKE_ID,
                'sheet_name': 'FakeSheet',
                'document_type': 'quote_request',
                'snapshot_method': 'connector_formula_values',
                'rows': [['商品名', 'JAN', 'ASIN'],
                         ['架空Sheets商品', FAKE_JAN, FAKE_ASIN]],
            }],
        }

    def run_probe(self, **kwargs):
        return inspect_private_connector_mixed(
            root_dir=self.root,
            excel_manifest=kwargs.get('excel_manifest', self.excel),
            connector_sheet_manifest=kwargs.get('connector_sheet_manifest',
                                                self.sheets),
            search=kwargs.get('search'),
        )

    def test_cross_format_jan_search_with_no_credentials(self):
        result = self.run_probe(search={'field': 'jan', 'query': FAKE_JAN})
        summary = result['public_summary']
        self.assertEqual(summary['source_kind_counts'],
                         {'excel': 1, 'sheets': 1})
        self.assertEqual(summary['record_count'], 2)
        self.assertEqual(result['public_search_summary']['hits_returned'], 2)
        self.assertEqual(summary['api_calls'], 0)
        self.assertFalse(summary['upstream_connector_auth_verified_by_this_function'])
        self.assertFalse(summary['python_google_api_auth_verified'])
        self.assertFalse(result['private_details_returned'])
        self.assertEqual((self.root / 'fake.xlsx').read_bytes(),
                         self.original_bytes)

    def test_does_not_leak_source_rows_or_identifiers(self):
        result = self.run_probe(search={'field': 'asin', 'query': FAKE_ASIN})
        public = json.dumps(result, ensure_ascii=False)
        for private in (FAKE_JAN, FAKE_ASIN, FAKE_ID, 'FakeSheet',
                        'FakeQuote', 'fake.xlsx', '架空Excel商品',
                        '架空Sheets商品', str(self.root)):
            self.assertNotIn(private, public)
        self.assertNotIn('private_hits', result)
        self.assertNotIn('private_normalized_docs', result)

    def test_no_search_is_safe(self):
        result = self.run_probe()
        self.assertIsNone(result['public_search_summary'])
        self.assertEqual(result['public_summary']['source_count'], 2)
        self.assertFalse(result['public_summary']['profit_calculation_allowed'])
        self.assertFalse(result['public_summary']['purchase_allowed'])

    def test_combined_limit_rejects_six_before_excel_read(self):
        source = self.sheets['sources'][0]
        enlarged = deepcopy(self.sheets)
        enlarged['sources'] = [
            dict(source, sheet_name=f'Sheet{i}')
            for i in range(5)
        ]
        with self.assertRaises(ValueError):
            self.run_probe(connector_sheet_manifest=enlarged)
        self.assertEqual((self.root / 'fake.xlsx').read_bytes(),
                         self.original_bytes)

    def test_invalid_search_rejected_before_excel_read(self):
        with self.assertRaises(ValueError):
            self.run_probe(search={'field': 'jan', 'query': 'bad_jan'})
        self.assertEqual((self.root / 'fake.xlsx').read_bytes(),
                         self.original_bytes)

    def test_oversized_sheet_cell_rejected(self):
        bad = deepcopy(self.sheets)
        bad['sources'][0]['rows'][1][0] = 'a' * 4001
        with self.assertRaises(ValueError):
            self.run_probe(connector_sheet_manifest=bad)

    def test_duplicate_connector_tabs_rejected(self):
        bad = deepcopy(self.sheets)
        bad['sources'].append(deepcopy(bad['sources'][0]))
        with self.assertRaises(ValueError):
            self.run_probe(connector_sheet_manifest=bad)

    def test_original_manifests_are_not_mutated(self):
        original = deepcopy((self.excel, self.sheets))
        self.run_probe()
        self.assertEqual((self.excel, self.sheets), original)

    def test_native_export_route_stays_non_decisive(self):
        other = deepcopy(self.sheets)
        other['sources'][0]['snapshot_method'] = 'native_export_xlsx'
        result = self.run_probe(connector_sheet_manifest=other)
        self.assertFalse(result['public_summary']['profit_calculation_allowed'])
        self.assertFalse(result['public_summary']['purchase_allowed'])


    def test_numeric_jan_from_two_different_header_rows_needs_review(self):
        # Synthetic geometry based on two REAL-world classes of quote sheet:
        # one with row-14 headers, the other with row-1 headers.
        # Never embed any supplier's actual JAN, name or price in CI.
        synthetic = Workbook()
        page = synthetic.active
        page.title = 'Header14'
        page.cell(row=14, column=2, value='商品名')
        page.cell(row=14, column=13, value='JAN')
        page.cell(row=15, column=2, value='架空の卸見積商品')
        page.cell(row=15, column=13, value=4901234567894)
        synthetic.save(self.root / 'header14.xlsx')
        synthetic.close()
        original = (self.root / 'header14.xlsx').read_bytes()

        excel = deepcopy(self.excel)
        excel['targets'][0].update({
            'relative_path': 'header14.xlsx',
            'sheet_name': 'Header14',
            'header_row': 14,
        })
        sheets = deepcopy(self.sheets)
        sheets['sources'][0].update({
            'rows': [
                ['商品名', 'JAN'],
                ['架空のSheets商品', 4901234567894],
            ],
            'snapshot_method': 'native_export_xlsx',
        })
        result = self.run_probe(
            excel_manifest=excel, connector_sheet_manifest=sheets,
            search={'field': 'jan', 'query': '4901234567894'})
        summary = result['public_summary']
        # Numeric values remain searchable candidates; they do NOT prove
        # preservation of leading zero or product identity.
        self.assertGreaterEqual(
            summary['numeric_jan_candidates_require_review'], 2)
        self.assertEqual(
            summary['native_sheet_exports_require_formula_review'], 1)
        self.assertFalse(summary['source_formula_fidelity_verified'])
        self.assertFalse(summary['native_export_price_or_lot_trust_allowed'])
        self.assertEqual(summary['confirmed_product_matches'], 0)
        self.assertFalse(summary['profit_calculation_allowed'])
        self.assertFalse(result['public_search_summary']['product_identity_confirmed'])
        self.assertEqual((self.root / 'header14.xlsx').read_bytes(), original)
        public = json.dumps(result, ensure_ascii=False)
        self.assertNotIn('4901234567894', public)
        self.assertNotIn('架空の卸見積商品', public)
        self.assertNotIn('架空のSheets商品', public)

    def test_safe_fidelity_fields_also_present_for_live_formula_snapshot(self):
        result = self.run_probe()
        summary = result['public_summary']
        self.assertEqual(summary['numeric_jan_candidates_require_review'], 0)
        self.assertEqual(summary['native_sheet_exports_require_formula_review'], 0)
        self.assertFalse(summary['source_formula_fidelity_verified'])
        self.assertFalse(summary['native_export_price_or_lot_trust_allowed'])


    def test_live_formula_snapshot_counts_literals_without_executing(self):
        sheets = deepcopy(self.sheets)
        sheets['sources'][0]['rows'][1].append('=2+2')
        result = self.run_probe(connector_sheet_manifest=sheets)
        summary = result['public_summary']
        self.assertEqual(summary['formula_cells_in_supplied_sheet_windows'], 1)
        self.assertTrue(summary['formula_cell_values_not_evaluated'])
        self.assertFalse(summary['source_formula_fidelity_verified'])
        self.assertFalse(summary['profit_calculation_allowed'])
        self.assertNotIn('=2+2', json.dumps(result))
        self.assertEqual((self.root / 'fake.xlsx').read_bytes(), self.original_bytes)

    def test_native_export_formula_count_is_observed_not_verified(self):
        sheets = deepcopy(self.sheets)
        sheets['sources'][0]['snapshot_method'] = 'native_export_xlsx'
        sheets['sources'][0]['rows'][1].append('=2+2')
        result = self.run_probe(connector_sheet_manifest=sheets)
        summary = result['public_summary']
        self.assertEqual(summary['formula_cells_in_supplied_sheet_windows'], 1)
        self.assertEqual(summary['native_sheet_exports_require_formula_review'], 1)
        self.assertFalse(summary['source_formula_fidelity_verified'])
        self.assertFalse(summary['native_export_price_or_lot_trust_allowed'])


if __name__ == '__main__':
    unittest.main()
