"""Synthetic-only tests: on-demand Google Sheets supplier lookup without Excel."""
from copy import deepcopy
import json
import unittest

from supplier_docs.connector_sheets_on_demand import (
    inspect_selected_connector_sheets,
    inspect_selected_connector_sheets_for_review,
)
from supplier_docs.connector_sheet_snapshot import SCHEMA_VERSION, MODE


JAN = '0000000000017'
ASIN = 'B0TEST0001'
FILE_A = 'SYNTHETIC_SHEET_A_001'
FILE_B = 'SYNTHETIC_SHEET_B_002'
CONTEXT = {
    'source_access_checked': True,
    'private_recipient_checked': True,
    'private_display_requested': True,
    'no_public_logging': True,
}


def manifest(method='connector_formula_values'):
    return {
        'schema_version': SCHEMA_VERSION, 'mode': MODE,
        'sources': [
            {'spreadsheet_id': FILE_A, 'sheet_name': '見積もり',
             'document_type': 'quote_request',
             'snapshot_method': method,
             'rows': [['商品名', 'JAN', 'ASIN', '単価'],
                      ['架空取引先Aの商品', JAN, ASIN, 123],
                      ['架空取引先Aの別商品', '4901234567894', 'B0TEST0002', 999]]},
            {'spreadsheet_id': FILE_B, 'sheet_name': '商品一覧',
             'document_type': 'quote_request',
             'snapshot_method': method,
             'rows': [['商品名', 'JAN', 'ASIN', '単価'],
                      ['架空取引先Bの商品', JAN, ASIN, '=2+2']]},
        ],
    }


class OnDemandSheetTests(unittest.TestCase):
    def anonymous(self, source=None, search=None):
        return inspect_selected_connector_sheets(
            connector_sheet_manifest=source or manifest(), search=search)

    def private(self, source=None, search=None, context=None, **kwargs):
        return inspect_selected_connector_sheets_for_review(
            connector_sheet_manifest=source if source is not None else manifest(),
            search=search if search is not None else {'field': 'jan', 'query': JAN},
            reviewer_context=context if context is not None else CONTEXT,
            **kwargs)

    def test_sheet_only_without_any_excel_dependency(self):
        result = self.anonymous(search={'field': 'jan', 'query': JAN})
        self.assertEqual(result['public_summary']['source_count'], 2)
        self.assertEqual(result['public_summary']['source_kind'], 'sheets')
        self.assertEqual(result['public_summary']['record_count'], 3)
        self.assertEqual(result['public_search_summary']['hits_returned'], 2)
        self.assertFalse(result['private_details_returned'])

    def test_single_tab_without_excel(self):
        conf = manifest()
        conf['sources'].pop()
        result = self.anonymous(source=conf, search={'field':'asin','query':ASIN})
        self.assertEqual(result['public_summary']['source_count'],1)
        self.assertEqual(result['public_search_summary']['hits_returned'],1)

    def test_public_never_exposes_private_identifiers_names_or_formula(self):
        result = self.anonymous(search={'field':'asin','query':ASIN})
        payload=json.dumps(result,ensure_ascii=False)
        for hidden in (FILE_A,FILE_B, '見積もり','商品一覧',JAN,ASIN,
                       '架空取引先Aの商品','架空取引先Bの商品','=2+2', '123','999'):
            self.assertNotIn(hidden,payload)
        self.assertNotIn('private_hits',result)
        self.assertFalse(result['public_summary']['all_supplier_folders_searched'])
        self.assertFalse(result['public_summary']['python_google_api_auth_verified'])

    def test_live_formula_count_observed_not_executed(self):
        result=self.anonymous()
        self.assertEqual(result['public_summary']['formula_cells_in_supplied_sheet_windows'],1)
        self.assertTrue(result['public_summary']['formula_cell_values_not_evaluated'])
        self.assertFalse(result['public_summary']['source_formula_fidelity_verified'])

    def test_private_two_sheets_have_verbatim_sources_and_rows(self):
        urls = [
            'https://docs.google.com/spreadsheets/d/' + fid + '/edit'
            for fid in (FILE_A,FILE_B)
        ]
        report=self.private(
            source_labels=['架空の取引先A', '架空の取引先B'],
            sheet_gid_by_url={urls[0]:7,urls[1]:25})
        self.assertEqual(report['matched_hits_total'],2)
        self.assertEqual(report['hits_displayed'],2)
        hits=report['private_hits']
        self.assertEqual([h['product_name'] for h in hits],
                         ['架空取引先Aの商品','架空取引先Bの商品'])
        self.assertEqual([h['jan_candidate'] for h in hits],[JAN,JAN])
        self.assertEqual([h['original_physical_row'] for h in hits],[2,2])
        self.assertEqual([h['original_row_url'] for h in hits],
                         [urls[0]+'#gid=7&range=A2:O2',
                          urls[1]+'#gid=25&range=A2:O2'])
        self.assertTrue(all(h['label_provenance']=='caller_declared_unverified' for h in hits))
        self.assertTrue(all(h['candidate_only'] and not h['identifier_or_selling_unit_confirmed']
                            for h in hits))
        self.assertFalse(report['user_identity_verified_by_this_function'])
        self.assertFalse(report['source_access_verified_by_this_function'])
        self.assertFalse(report['price_disclosure_allowed'])

    def test_private_without_gid_does_not_fabricate_deep_links(self):
        report=self.private()
        self.assertEqual(report['hits_displayed'],2)
        self.assertTrue(all(h['original_row_url'] is None for h in report['private_hits']))

    def test_explicit_private_review_required_even_with_valid_sources(self):
        for bad in (None, {}, {**CONTEXT,'no_public_logging':False}):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                inspect_selected_connector_sheets_for_review(
                    connector_sheet_manifest=manifest(),
                    search={'field':'jan','query':JAN},
                    reviewer_context=bad)

    def test_authorization_preflight_precedes_source_parser(self):
        with self.assertRaisesRegex(ValueError,'private review'):
            inspect_selected_connector_sheets_for_review(
                connector_sheet_manifest={'malformed':'source'},
                search={'field':'jan','query':JAN},
                reviewer_context={})

    def test_truncation_is_not_hidden(self):
        result=self.private(max_hits=1)
        self.assertEqual(result['matched_hits_total'],2)
        self.assertEqual(result['hits_displayed'],1)
        self.assertTrue(result['hits_truncated_for_review'])

    def test_zero_hits_never_claims_full_drive_search(self):
        result=self.private(search={'field':'jan','query':'0000000000099'})
        self.assertEqual(result['matched_hits_total'],0)
        self.assertFalse(result['all_supplier_folders_searched'])

    def test_rejects_unselected_or_noninteger_gid(self):
        url='https://docs.google.com/spreadsheets/d/'+FILE_A+'/edit'
        for mapping in ({'https://docs.google.com/spreadsheets/d/OTHER/edit':1},
                        {url:True},{url:'0'},{url:-1}):
            with self.subTest(mapping=mapping),self.assertRaises(ValueError):
                self.private(sheet_gid_by_url=mapping)

    def test_native_export_remains_price_unverified(self):
        conf=manifest('native_export_xlsx')
        for source in conf['sources']:
            source['document_type']='quote_response'
            source['rows'][0][3]='下代（税抜）'
        result=self.anonymous(source=conf)
        self.assertGreaterEqual(
            result['public_summary']['native_export_cost_flags_suppressed'],1)
        self.assertTrue(result['public_summary']['xlsx_export_type_fidelity_requires_review'])
        self.assertFalse(result['public_summary']['native_export_price_or_lot_trust_allowed'])
        self.assertFalse(result['public_summary']['purchase_allowed'])

    def test_duplicate_selected_sheet_refused(self):
        conf=manifest()
        conf['sources'].append(deepcopy(conf['sources'][0]))
        with self.assertRaises(ValueError):
            self.anonymous(source=conf)

    def test_five_tab_maximum_and_search_validation(self):
        conf=manifest()
        conf['sources']=[
            dict(conf['sources'][0],sheet_name=f'Tab{i}') for i in range(6)
        ]
        with self.assertRaises(ValueError):
            self.anonymous(source=conf)
        for q in ({'field':'jan','query':'not-a-jan'},
                  {'field':'password','query':'abc'}, {'field':'jan','query':JAN,'price':True}):
            with self.assertRaises(ValueError):
                self.anonymous(search=q)

    def test_user_input_and_private_rows_never_mutated(self):
        conf=manifest()
        original=deepcopy(conf)
        self.anonymous(source=conf,search={'field':'jan','query':JAN})
        self.private(source=conf)
        self.assertEqual(conf,original)


if __name__=='__main__':
    unittest.main()
