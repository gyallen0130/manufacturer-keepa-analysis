"""Synthetic-only contiguous Google Sheets paging regressions.

All sources and products are fictional. No Google auth, network or logs.
"""
from copy import deepcopy
import json
import unittest

from supplier_docs.connector_sheets_paged import (
    SCHEMA_VERSION, MODE,
    inspect_selected_connector_sheet_pages,
    inspect_selected_connector_sheet_pages_for_review,
)

ID1 = 'SYNTHETIC_SHEET_A_001'
ID2 = 'SYNTHETIC_SHEET_B_002'
JAN = '0000000000017'
JAN2 = '4901234567894'
ASIN = 'B0TEST0001'
CONTEXT = {
    'source_access_checked': True,
    'private_recipient_checked': True,
    'private_display_requested': True,
    'no_public_logging': True,
}


def source(*, file_id=ID1, tab='架空シート', pages=2):
    result = {
        'spreadsheet_id': file_id,
        'sheet_name': tab,
        'document_type': 'quote_request',
        'snapshot_method': 'connector_formula_values',
        'header_row': 1,
        'header_rows': [['商品名', 'JAN', 'ASIN', '下代（税抜）']],
        'pages': [],
    }
    for i in range(pages):
        start = 2 + i*39
        end = start + 38
        rows = [
            [f'架空商品{row}', JAN if row == 41 else str(4901234500000+row),
             ASIN if row in (41,79) else f'B0{i:08d}', 987]
            for row in range(start, end + 1)
        ]
        result['pages'].append({'start_row':start,'end_row':end,'rows':rows})
    return result


def manifest(*, sources=None):
    return {
        'schema_version': SCHEMA_VERSION, 'mode': MODE,
        'sources': sources if sources is not None else [source()],
    }


class PagedSourceTests(unittest.TestCase):
    def public(self, conf=None, search=None):
        return inspect_selected_connector_sheet_pages(
            manifest=conf if conf is not None else manifest(), search=search)

    def private(self, conf=None, search=None, context=CONTEXT, **kwargs):
        return inspect_selected_connector_sheet_pages_for_review(
            manifest=conf if conf is not None else manifest(),
            search=search if search is not None else {'field':'jan','query':JAN},
            reviewer_context=context, **kwargs)

    def test_second_page_exact_41st_row_and_gid_link(self):
        query={'field':'jan','query':JAN}
        public=self.public(search=query)
        self.assertEqual(public['public_summary']['source_count'],1)
        self.assertEqual(public['public_summary']['page_count'],2)
        self.assertEqual(public['public_summary']['rows_requested_excluding_header'],78)
        self.assertEqual(public['public_summary']['record_count'],78)
        self.assertEqual(public['public_search_summary']['hits_returned'],1)
        url='https://docs.google.com/spreadsheets/d/'+ID1+'/edit'
        report=self.private(search=query,sheet_gid_by_url={url:1357})
        self.assertEqual(report['hits_displayed'],1)
        hit=report['private_hits'][0]
        self.assertEqual(hit['product_name'],'架空商品41')
        self.assertEqual(hit['original_physical_row'],41)
        self.assertEqual(hit['original_row_url'],
                         url+'#gid=1357&range=A41:O41')
        self.assertTrue(hit['candidate_only'])
        self.assertFalse(hit['identifier_or_selling_unit_confirmed'])

    def test_late_79th_row_search(self):
        report=self.private(search={'field':'product','query':'架空商品79'})
        self.assertEqual(report['hits_displayed'],1)
        self.assertEqual(report['private_hits'][0]['original_physical_row'],79)

    def test_numeric_jan_warning_maps_to_original_physical_row(self):
        conf=manifest()
        conf['sources'][0]['pages'][1]['rows'][0][1] = 4901234567894
        report=self.private(conf=conf, search={'field':'jan','query':JAN2})
        self.assertEqual(report['hits_displayed'],1)
        hit=report['private_hits'][0]
        self.assertEqual(hit['original_physical_row'],41)
        self.assertIn('JAN_NUMERIC_CELL',hit['warning_codes'])
        self.assertFalse(hit['identifier_or_selling_unit_confirmed'])
        public=self.public(conf=conf)
        self.assertEqual(public['public_summary']['numeric_jan_candidates_require_review'],1)

    def test_public_redaction_includes_no_source_ids_or_products(self):
        result=self.public(search={'field':'jan','query':JAN})
        raw=json.dumps(result,ensure_ascii=False)
        for token in (ID1,'架空シート','架空商品41',JAN,ASIN,'987','A41'):
            self.assertNotIn(token,raw)
        self.assertFalse(result['public_summary']['all_rows_in_selected_tabs_searched'])
        self.assertFalse(result['public_summary']['all_supplier_folders_searched'])
        self.assertFalse(result['private_details_returned'])

    def test_missing_page_is_rejected_not_false_zero_hits(self):
        conf=manifest()
        conf['sources'][0]['pages'].pop(0)
        with self.assertRaisesRegex(ValueError,'noncontiguous'):
            self.public(conf=conf)

    def test_overlap_or_gap_between_pages_is_rejected(self):
        for change in (40,42):
            with self.subTest(change=change):
                conf=manifest()
                conf['sources'][0]['pages'][1]['start_row']=change
                with self.assertRaisesRegex(ValueError,'noncontiguous'):
                    self.public(conf=conf)

    def test_five_page_budget_and_six_page_rejection(self):
        five=manifest(sources=[source(pages=5)])
        ok=self.public(conf=five)
        self.assertEqual(ok['public_summary']['page_count'],5)
        self.assertEqual(ok['public_summary']['rows_requested_excluding_header'],195)
        six=manifest(sources=[source(pages=6)])
        with self.assertRaisesRegex(ValueError,'budget'):
            self.public(conf=six)

    def test_multiple_sources_are_merged_not_counted_as_duplicate_tabs(self):
        conf=manifest(sources=[
            source(file_id=ID1,tab='見積'),
            source(file_id=ID2,tab='一覧'),
        ])
        url1='https://docs.google.com/spreadsheets/d/'+ID1+'/edit'
        url2='https://docs.google.com/spreadsheets/d/'+ID2+'/edit'
        response=self.private(conf=conf,source_labels=['架空A','架空B'],
                             sheet_gid_by_url={url1:7,url2:9})
        self.assertEqual(response['matched_hits_total'],2)
        self.assertEqual([hit['original_physical_row']
                          for hit in response['private_hits']], [41,41])
        self.assertEqual([hit['source_kind']
                          for hit in response['private_hits']],['sheets','sheets'])
        self.assertEqual(response['private_hits'][1]['original_row_url'],
                         url2+'#gid=9&range=A41:O41')

    def test_missing_trailing_rows_are_explicit_blank_padding(self):
        conf=manifest()
        second=conf['sources'][0]['pages'][1]
        second['rows']=second['rows'][:1]
        result=self.public(conf=conf,search={'field':'jan','query':JAN})
        self.assertEqual(result['public_summary']['trailing_rows_unpopulated_in_connector_response'],38)
        self.assertEqual(result['public_search_summary']['hits_returned'],1)
        self.assertEqual(result['public_summary']['record_count'],40)
        self.assertFalse(result['public_summary']['all_rows_in_selected_tabs_searched'])

    def test_same_sheet_tab_cannot_repeat(self):
        conf=manifest(sources=[source(),source()])
        with self.assertRaisesRegex(ValueError,'duplicate'):
            self.public(conf=conf)

    def test_header_row_14_and_page_2_position_are_preserved(self):
        src=source(pages=0)
        src['header_row']=14
        src['header_rows']=[[] for _ in range(13)]+[['商品名','JAN','ASIN']]
        src['pages']=[
            {'start_row':15,'end_row':40,
             'rows':[[f'架空H14商品{r}','4901234567894',ASIN]
                     for r in range(15,41)]},
            {'start_row':41,'end_row':66,
             'rows':[[f'架空H14商品{r}',JAN,ASIN]
                     for r in range(41,67)]},
        ]
        result=self.private(conf=manifest(sources=[src]),search={'field':'jan','query':JAN})
        self.assertEqual(result['matched_hits_total'],26)
        self.assertEqual(result['hits_displayed'],20)
        self.assertTrue(result['hits_truncated_for_review'])
        self.assertEqual(result['private_hits'][0]['original_physical_row'],41)
        # PRIVATE detail display is deliberately capped at 20 records.
        self.assertEqual(result['private_hits'][-1]['original_physical_row'],60)

    def test_header_formula_counted_once_even_when_repeated_for_parsing(self):
        conf=manifest()
        conf['sources'][0]['header_rows'][0][3] = '=100+2'
        conf['sources'][0]['pages'][1]['rows'][0][3] = '=10+4'
        result=self.public(conf=conf)
        self.assertEqual(result['public_summary']['formula_cells_in_supplied_sheet_windows'],2)
        self.assertFalse(result['public_summary']['source_formula_fidelity_verified'])

    def test_incomplete_private_authorization_rejected_before_source_validation(self):
        with self.assertRaisesRegex(ValueError,'private review'):
            self.private(conf={'invalid':'manifest'},context={})

    def test_rejects_unknown_keys_wrong_types_and_bad_rows(self):
        for modification in ('unknown','bool','bad_header','oversize','wrong_cells'):
            with self.subTest(modification=modification):
                conf=manifest()
                src=conf['sources'][0]
                if modification=='unknown':
                    src['secret']='token'
                elif modification=='bool':
                    src['pages'][0]['start_row']=True
                elif modification=='bad_header':
                    src['header_row']=2
                elif modification=='oversize':
                    src['pages'][0]['end_row']=41
                else:
                    src['pages'][0]['rows'][0][0]={'secret':'value'}
                with self.assertRaises(ValueError):
                    self.public(conf=conf)

    def test_zero_matches_do_not_claim_full_sheet_searched(self):
        result=self.public(search={'field':'jan','query':'0000000000099'})
        self.assertEqual(result['public_search_summary']['hits_returned'],0)
        self.assertFalse(result['public_summary']['all_rows_in_selected_tabs_searched'])

    def test_original_manifest_and_rows_not_modified(self):
        conf=manifest()
        old=deepcopy(conf)
        self.public(conf=conf,search={'field':'jan','query':JAN})
        self.private(conf=conf)
        self.assertEqual(conf,old)

    def test_explicit_zero_results_safe_and_price_not_returned(self):
        conf=manifest()
        x=self.private(conf=conf,search={'field':'jan','query':'0000000000099'})
        self.assertEqual(x['hits_displayed'],0)
        self.assertFalse(x['purchase_allowed'])
        self.assertFalse(x['price_disclosure_allowed'])

    def test_unverified_gid_never_invents_row_link(self):
        hits=self.private()['private_hits']
        self.assertEqual(len(hits),1)
        self.assertIsNone(hits[0]['original_row_url'])


    def test_unlabeled_profit_inference_may_vary_across_pages_only(self):
        src=source(pages=0)
        src['header_rows']=[['商品名','JAN','','']]
        src['pages']=[
            {'start_row':2,'end_row':7,
             'rows':[[f'架空行{r}',JAN,ASIN,'黒字'] for r in range(2,8)]},
            {'start_row':8,'end_row':13,
             'rows':[[f'架空行{r}',JAN,ASIN,'未判定'] for r in range(8,14)]},
        ]
        result=self.private(conf=manifest(sources=[src]),
                            search={'field':'asin','query':ASIN})
        self.assertEqual(result['matched_hits_total'],12)
        self.assertEqual(result['private_hits'][-1]['original_physical_row'],13)
        self.assertFalse(result['price_disclosure_allowed'])
        self.assertFalse(result['profit_calculation_allowed'])

    def test_changed_inferred_asin_column_is_rejected_across_pages(self):
        src=source(pages=0)
        src['header_rows']=[['商品名','JAN','','']]
        src['pages']=[
            {'start_row':2,'end_row':7,
             'rows':[[f'架空行{r}',JAN,ASIN,'黒字'] for r in range(2,8)]},
            {'start_row':8,'end_row':13,
             'rows':[[f'架空行{r}',JAN,'ASIN不明','未判定']
                     for r in range(8,14)]},
        ]
        with self.assertRaisesRegex(ValueError,'mapping changed'):
            self.public(conf=manifest(sources=[src]))


if __name__ == '__main__':
    unittest.main()
