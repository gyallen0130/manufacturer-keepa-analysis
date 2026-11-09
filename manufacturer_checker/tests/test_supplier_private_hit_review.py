"""Offline synthetic tests for explicit private-only supplier hit review."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from openpyxl import Workbook

from supplier_docs.connector_mixed_one_shot import (
    inspect_private_connector_mixed,
    inspect_private_connector_mixed_for_review,
)
from supplier_docs.local_excel_bridge import (
    SCHEMA_VERSION as XLS_SCHEMA, MODE as XLS_MODE,
    inspect_selected_local_excel,
)
from supplier_docs.connector_sheet_snapshot import (
    SCHEMA_VERSION as SHEET_SCHEMA, MODE as SHEET_MODE,
    normalize_selected_connector_snapshots,
)
from supplier_docs.mixed_source_readonly import combine_selected_source_results
from supplier_docs.private_hit_review import prepare_selected_private_hit_review


JAN = '0000000000017'
ASIN = 'B0TEST0001'
SHEET_ID = 'SYNTHETIC_SHEET_ID_001'
PRIVATE_CONTEXT = {
    'source_access_checked': True,
    'private_recipient_checked': True,
    'private_display_requested': True,
    'no_public_logging': True,
}


class PrivateHitReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        workbook = Workbook()
        tab = workbook.active
        tab.title = 'Quotation'
        tab.append(['商品名', 'JAN', 'ASIN', '単価'])
        tab.append(['架空Excel部品', JAN, ASIN, 731])
        workbook.save(self.root / 'quote.xlsx')
        workbook.close()
        self.before = (self.root / 'quote.xlsx').read_bytes()
        self.excel = {
            'schema_version': XLS_SCHEMA, 'mode': XLS_MODE,
            'targets': [{'relative_path': 'quote.xlsx',
                         'sheet_name': 'Quotation',
                         'document_type': 'quote_request'}],
        }
        self.sheets = {
            'schema_version': SHEET_SCHEMA, 'mode': SHEET_MODE,
            'sources': [{
                'spreadsheet_id': SHEET_ID,
                'sheet_name': 'Sample',
                'document_type': 'quote_request',
                'snapshot_method': 'connector_formula_values',
                'rows': [['商品名', 'JAN', 'ASIN', '単価'],
                         ['架空Sheets部品', JAN, ASIN, 928]],
            }],
        }
        self.search = {'field': 'jan', 'query': JAN}

    def review(self, *, search=None, context=None, labels=None, **extra):
        return inspect_private_connector_mixed_for_review(
            root_dir=self.root,
            excel_manifest=self.excel,
            connector_sheet_manifest=self.sheets,
            search=self.search if search is None else search,
            reviewer_context=PRIVATE_CONTEXT if context is None else context,
            source_labels=labels, **extra)

    def combined(self):
        excel = inspect_selected_local_excel(
            root_dir=self.root, manifest=self.excel)
        sheets = normalize_selected_connector_snapshots(manifest=self.sheets)
        return combine_selected_source_results([excel, sheets],
                                               search=self.search)

    def test_explicit_private_view_contains_only_selected_hit_evidence(self):
        report = self.review(labels=['架空Excel取引先', '架空Sheets取引先'])
        self.assertEqual(report['privacy_classification'],
                         'PRIVATE_USER_ONLY_NEVER_LOG')
        self.assertEqual(report['matched_hits_total'], 2)
        self.assertEqual(report['hits_displayed'], 2)
        self.assertFalse(report['hits_truncated_for_review'])
        self.assertFalse(report['user_identity_verified_by_this_function'])
        self.assertFalse(report['source_access_verified_by_this_function'])
        self.assertTrue(report['selected_source_only'])
        hits = report['private_hits']
        self.assertEqual([h['source_kind'] for h in hits], ['excel','sheets'])
        self.assertEqual(hits[0]['supplier_or_source_label'], '架空Excel取引先')
        self.assertEqual(hits[0]['original_file_path'], 'quote.xlsx')
        self.assertEqual(hits[0]['original_physical_row'], 2)
        self.assertIsNone(hits[0]['original_sheet_url'])
        self.assertEqual(hits[1]['original_sheet_tab'], 'Sample')
        self.assertEqual(hits[1]['original_physical_row'], 2)
        self.assertEqual(hits[1]['original_sheet_url'],
                         'https://docs.google.com/spreadsheets/d/'
                         + SHEET_ID + '/edit')
        self.assertEqual([h['product_name'] for h in hits],
                         ['架空Excel部品', '架空Sheets部品'])
        self.assertEqual([h['jan_candidate'] for h in hits], [JAN,JAN])
        self.assertTrue(all(h['candidate_only'] for h in hits))
        self.assertTrue(all(not h['identifier_or_selling_unit_confirmed']
                            for h in hits))
        self.assertTrue(all(not h['purchase_allowed'] for h in hits))
        self.assertEqual((self.root / 'quote.xlsx').read_bytes(), self.before)

    def test_default_public_one_shot_still_has_no_private_names_or_origins(self):
        response = inspect_private_connector_mixed(
            root_dir=self.root, excel_manifest=self.excel,
            connector_sheet_manifest=self.sheets, search=self.search)
        public = json.dumps(response, ensure_ascii=False)
        self.assertFalse(response['private_details_returned'])
        for secret in [JAN, ASIN, SHEET_ID, 'quote.xlsx', 'Quotation',
                       '架空Excel部品', '架空Sheets部品', '731', '928']:
            self.assertNotIn(secret, public)
        self.assertNotIn('private_hits', response)

    def test_missing_private_confirmation_fails_before_excel_read(self):
        for context in (None, {}, {'private_display_requested': True},
                        {**PRIVATE_CONTEXT, 'no_public_logging': False}):
            with self.subTest(context=context):
                with self.assertRaises(ValueError):
                    inspect_private_connector_mixed_for_review(
                        root_dir='/definitely-not-a-valid-file-root',
                        excel_manifest=self.excel,
                        connector_sheet_manifest=self.sheets,
                        search=self.search,
                        reviewer_context=context)

    def test_source_labels_are_declared_not_verified(self):
        response = self.review(labels=['Excel A', 'Sheets B'])
        self.assertTrue(all(h['label_provenance']=='caller_declared_unverified'
                            for h in response['private_hits']))
        defaults = self.review()
        self.assertEqual(defaults['private_hits'][0]['supplier_or_source_label'],
                         'quote.xlsx')
        self.assertEqual(defaults['private_hits'][1]['supplier_or_source_label'],
                         'Sample')
        self.assertEqual(defaults['private_hits'][1]['label_provenance'],
                         'source_file_or_tab')

    def test_bad_labels_and_limit_fail(self):
        for labels in (['one'], ['one','two','three'], ['one',''],
                       ['one','two\nsecret']):
            with self.subTest(labels=labels):
                with self.assertRaises(ValueError):
                    self.review(labels=labels)
        for limit in (0,21,True,-1):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    self.review(max_hits=limit)

    def test_private_hit_limit_and_truncation_visible(self):
        response = self.review(max_hits=1)
        self.assertEqual(response['matched_hits_total'],2)
        self.assertEqual(response['hits_displayed'],1)
        self.assertTrue(response['hits_truncated_for_review'])
        self.assertEqual(len(response['private_hits']),1)

    def test_asin_lookup_matches_both_without_inventing_manufacturer(self):
        response = self.review(search={'field':'asin','query':ASIN})
        self.assertEqual(response['matched_hits_total'],2)
        self.assertTrue(all(h['manufacturer_name']=='' for h in response['private_hits']))
        self.assertTrue(all(h['asin_candidates']==[ASIN]
                            for h in response['private_hits']))

    def test_unmatched_query_does_not_claim_global_absence(self):
        response = self.review(search={'field':'jan','query':'0000000000099'})
        self.assertEqual(response['matched_hits_total'],0)
        self.assertEqual(response['private_hits'],[])
        self.assertFalse(response['all_supplier_folders_searched'])

    def test_forged_or_stale_hit_pointer_rejected(self):
        combined=self.combined()
        combined['private_hits'][0]['source_row']=30
        with self.assertRaises(ValueError):
            prepare_selected_private_hit_review(
                combined=combined,search=self.search,
                reviewer_context=PRIVATE_CONTEXT)

    def test_swapped_origin_mapping_rejected(self):
        combined=self.combined()
        combined['private_source_origins']=list(
            reversed(combined['private_source_origins']))
        with self.assertRaises(ValueError):
            prepare_selected_private_hit_review(
                combined=combined,search=self.search,
                reviewer_context=PRIVATE_CONTEXT)

    def test_changed_search_rejected_even_with_existing_hits(self):
        combined=self.combined()
        with self.assertRaises(ValueError):
            prepare_selected_private_hit_review(
                combined=combined,
                search={'field':'asin','query':ASIN},
                reviewer_context=PRIVATE_CONTEXT)
        with self.assertRaises(ValueError):
            self.review(search={'field':'jan','query':'not-an-id'})

    def test_output_never_contains_cost_price_notes_or_unselected_source_rows(self):
        response=self.review()
        raw=json.dumps(response,ensure_ascii=False)
        self.assertNotIn('731',raw)
        self.assertNotIn('928',raw)
        self.assertNotIn('cost_amount',raw)
        self.assertNotIn('trade_terms',raw)
        self.assertNotIn(str(self.root),raw)
        self.assertFalse(response['profit_calculation_allowed'])
        self.assertFalse(response['price_disclosure_allowed'])
        self.assertEqual(response['source_writes'],0)

    def test_numeric_jan_warning_is_visible_but_identity_unconfirmed(self):
        workbook=Workbook()
        tab=workbook.active
        tab.title='Numeric'
        tab.append(['商品名','JAN'])
        tab.append(['架空の数値JAN',4901234567894])
        workbook.save(self.root/'numeric.xlsx')
        workbook.close()
        local = deepcopy(self.excel)
        local['targets'][0].update(relative_path='numeric.xlsx',
                                   sheet_name='Numeric')
        selected=inspect_private_connector_mixed_for_review(
            root_dir=self.root,
            excel_manifest=local,
            connector_sheet_manifest=self.sheets,
            search={'field':'jan','query':'4901234567894'},
            reviewer_context=PRIVATE_CONTEXT)
        self.assertEqual(selected['matched_hits_total'],1)
        hit=selected['private_hits'][0]
        self.assertIn('JAN_NUMERIC_CELL',hit['warning_codes'])
        self.assertFalse(hit['identifier_or_selling_unit_confirmed'])

    def test_formula_cell_does_not_become_price_or_command(self):
        new_sheets=deepcopy(self.sheets)
        new_sheets['sources'][0]['rows'][1][3]='=1+999'
        response=inspect_private_connector_mixed_for_review(
            root_dir=self.root,
            excel_manifest=self.excel,
            connector_sheet_manifest=new_sheets,
            search=self.search,
            reviewer_context=PRIVATE_CONTEXT)
        private=json.dumps(response,ensure_ascii=False)
        self.assertNotIn('=1+999',private)
        self.assertFalse(response['price_disclosure_allowed'])


    def test_legacy_private_result_without_excel_origin_rejects_view_only(self):
        excel = inspect_selected_local_excel(
            root_dir=self.root, manifest=self.excel)
        excel.pop('private_origin_manifest')
        sheets = normalize_selected_connector_snapshots(manifest=self.sheets)
        combined = combine_selected_source_results(
            [excel, sheets], search=self.search)
        self.assertEqual(combined['public_search_summary']['hits_returned'],2)
        with self.assertRaises(ValueError):
            prepare_selected_private_hit_review(
                combined=combined,search=self.search,
                reviewer_context=PRIVATE_CONTEXT)


    def test_authenticated_tab_gid_builds_only_selected_private_row_link(self):
        source_url = 'https://docs.google.com/spreadsheets/d/' + SHEET_ID + '/edit'
        review = self.review(sheet_gid_by_url={source_url: 56789})
        excel_hit, sheet_hit = review['private_hits']
        self.assertIsNone(excel_hit['original_row_url'])
        self.assertEqual(
            sheet_hit['original_row_url'],
            source_url + '#gid=56789&range=A2:O2')
        self.assertFalse(sheet_hit['row_link_gid_verified_by_this_function'])
        public = inspect_private_connector_mixed(
            root_dir=self.root, excel_manifest=self.excel,
            connector_sheet_manifest=self.sheets, search=self.search)
        self.assertNotIn('gid=56789', json.dumps(public))

    def test_unverified_gid_does_not_create_fake_row_url(self):
        hits = self.review()['private_hits']
        self.assertTrue(all(h['original_row_url'] is None for h in hits))

    def test_unselected_or_invalid_gid_mapping_rejected(self):
        source_url = 'https://docs.google.com/spreadsheets/d/' + SHEET_ID + '/edit'
        for mapping in [
            {'https://docs.google.com/spreadsheets/d/OTHER/edit': 1},
            {source_url: True},
            {source_url: '123'},
            {source_url: -1},
            {source_url: 2147483648},
            {source_url: 1.0},
            {source_url: 1, 'https://docs.google.com/spreadsheets/d/OTHER/edit': 2},
            [source_url, 123],
        ]:
            with self.subTest(mapping=mapping):
                with self.assertRaises(ValueError):
                    self.review(sheet_gid_by_url=mapping)


if __name__ == '__main__':
    unittest.main()
