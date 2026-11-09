"""Synthetic tests for safe on-demand manufacturer supplier Sheet range planning."""
from copy import deepcopy
import json
import unittest

from supplier_docs.supplier_query_planner import (
    plan_supplier_sheet_reads,
    build_private_page_manifest,
    summarize_plan_without_private_sources,
)
from supplier_docs.connector_sheets_paged import (
    inspect_selected_connector_sheet_pages,
    inspect_selected_connector_sheet_pages_for_review,
)

FILE_A = 'SYNTHETIC_CATALOG_A_0001'
FILE_B = 'SYNTHETIC_CATALOG_B_0002'
FILE_C = 'SYNTHETIC_CATALOG_C_0003'
JAN = '0000000000017'
ASIN = 'B0TEST0001'
AUTH = {
    'source_access_checked': True,
    'private_recipient_checked': True,
    'private_display_requested': True,
    'no_public_logging': True,
}


def entry(supplier='架空の仕入先A', file_id=FILE_A, tab='見積もり',
          row_count=998, header=1, gid=0):
    return {
        'supplier_label': supplier,
        'spreadsheet_id': file_id,
        'sheet_name': tab,
        'sheet_gid': gid,
        'grid_rows': row_count,
        'grid_columns': 30,
        'header_row': header,
        'document_type': 'quote_request',
        'visible': True,
        'source_access_checked': True,
    }


def fake_connector_responses(plan):
    responses = []
    for src in plan['selected_sources']:
        h = src['header_row']
        header = [[] for _ in range(h-1)] + [['商品名', 'JAN', 'ASIN']]
        responses.append({
            'spreadsheet_id': src['spreadsheet_id'],
            'sheet_name': src['sheet_name'],
            'requested_range': src['header_range'],
            'rows': header,
        })
        for p in src['data_pages']:
            rows = [[f'架空部品{line}',JAN if line == 41 else '4901234567894',
                     ASIN if line == 41 else 'B0TEST0002']
                    for line in range(p['start_row'], p['end_row']+1)]
            responses.append({
                'spreadsheet_id': src['spreadsheet_id'],
                'sheet_name': src['sheet_name'],
                'requested_range': p['requested_range'],
                'rows': rows,
            })
    return responses


class SupplierQueryPlannerTests(unittest.TestCase):
    def test_supplier_exact_and_unique_substring_match(self):
        approved = [entry(), entry('架空の仕入先B', FILE_B)]
        a = plan_supplier_sheet_reads(
            supplier_query='架空の仕入先A', approved_tab_metadata=approved)
        b = plan_supplier_sheet_reads(
            supplier_query='仕入先B', approved_tab_metadata=approved)
        self.assertEqual(a['selected_tabs'],1)
        self.assertEqual(b['selected_tabs'],1)
        self.assertEqual(a['selected_sources'][0]['spreadsheet_id'],FILE_A)
        self.assertEqual(b['selected_sources'][0]['spreadsheet_id'],FILE_B)
        self.assertFalse(a['source_access_verified_by_this_function'])

    def test_ambiguous_and_missing_supplier_rejected(self):
        approved = [entry(),entry('架空の仕入先B',FILE_B)]
        for q in ('架空の仕入先','存在しない卸', ''):
            with self.subTest(query=q), self.assertRaises(ValueError):
                plan_supplier_sheet_reads(
                    supplier_query=q,approved_tab_metadata=approved)

    def test_bounded_page_plan_from_header_row_one(self):
        x=plan_supplier_sheet_reads(supplier_query='架空の仕入先A',
                                   approved_tab_metadata=[entry()])
        source=x['selected_sources'][0]
        self.assertEqual(source['header_range'],'A1:O1')
        self.assertEqual(len(source['data_pages']),5)
        self.assertEqual(source['data_pages'][0],
                         {'start_row':2,'end_row':40,
                          'requested_range':'A2:O40'})
        self.assertEqual(source['data_pages'][1],
                         {'start_row':41,'end_row':79,
                          'requested_range':'A41:O79'})
        self.assertEqual(x['planned_data_rows'],195)
        self.assertTrue(x['unread_grid_rows_remain'])

    def test_explicit_header_fourteen_preserved(self):
        x=plan_supplier_sheet_reads(supplier_query='架空の仕入先A',
                                   approved_tab_metadata=[entry(header=14)])
        src=x['selected_sources'][0]
        self.assertEqual(src['header_range'],'A1:O14')
        self.assertEqual(src['data_pages'][0]['requested_range'],'A15:O40')
        self.assertEqual(src['data_pages'][1]['requested_range'],'A41:O66')
        self.assertEqual(x['planned_data_rows'],130)

    def test_two_tabs_round_robin_without_starvation(self):
        approved=[
            entry(file_id=FILE_A,tab='見積もり'),
            entry(file_id=FILE_B,tab='取扱メーカー',gid=30),
        ]
        x=plan_supplier_sheet_reads(supplier_query='架空の仕入先A',
                                   approved_tab_metadata=approved)
        self.assertEqual(x['selected_tabs'],2)
        self.assertEqual(x['planned_pages'],5)
        self.assertEqual([len(s['data_pages'])
                          for s in x['selected_sources']],[3,2])
        self.assertEqual(x['planned_data_rows'],195)

    def test_five_tabs_each_covered_once(self):
        approved=[entry(file_id=f'SYNTHETIC_CATALOG_{i:03d}_999',
                        tab=f'見積{i}',gid=i)
                  for i in range(5)]
        x=plan_supplier_sheet_reads(supplier_query='架空の仕入先A',
                                   approved_tab_metadata=approved)
        self.assertEqual([len(s['data_pages']) for s in x['selected_sources']],
                         [1]*5)

    def test_more_than_five_tabs_refused_no_silent_omission(self):
        approved=[entry(file_id=f'SYNTHETIC_CATALOG_{i:03d}_999',
                        tab=f'見積{i}',gid=i) for i in range(6)]
        with self.assertRaisesRegex(ValueError,'too many selected'):
            plan_supplier_sheet_reads(supplier_query='架空の仕入先A',
                                     approved_tab_metadata=approved)

    def test_hidden_unreadable_bad_gid_and_bool_count_fail(self):
        for k, v in [('visible',False),('source_access_checked',False),
                     ('sheet_gid',True),('sheet_gid',-1),
                     ('grid_rows',True),('grid_rows',1),
                     ('grid_columns',14),('header_row',True),
                     ('header_row',21),('document_type','arbitrary')]:
            with self.subTest(k=k,v=v):
                conf=entry()
                conf[k]=v
                with self.assertRaises(ValueError):
                    plan_supplier_sheet_reads(
                        supplier_query='架空の仕入先A',
                        approved_tab_metadata=[conf])

    def test_duplicate_catalog_tab_refused(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):
            plan_supplier_sheet_reads(
                supplier_query='架空の仕入先A',
                approved_tab_metadata=[entry(),deepcopy(entry())])

    def test_page_builder_binds_exact_ranges_even_out_of_order(self):
        plan=plan_supplier_sheet_reads(supplier_query='架空の仕入先A',
                                      approved_tab_metadata=[entry(row_count=79)])
        replies=fake_connector_responses(plan)
        replies.reverse()
        manifest=build_private_page_manifest(plan=plan,
                                             connector_responses=replies)
        self.assertEqual(len(manifest['sources']),1)
        self.assertEqual([x['start_row'] for x in manifest['sources'][0]['pages']],
                         [2,41])
        result=inspect_selected_connector_sheet_pages(
            manifest=manifest,search={'field':'jan','query':JAN})
        self.assertEqual(result['public_search_summary']['hits_returned'],1)
        self.assertEqual(result['public_summary']['record_count'],78)
        self.assertFalse(result['public_summary']['all_rows_in_selected_tabs_searched'])
        url=f'https://docs.google.com/spreadsheets/d/{FILE_A}/edit'
        private=inspect_selected_connector_sheet_pages_for_review(
            manifest=manifest,search={'field':'jan','query':JAN},
            reviewer_context=AUTH,sheet_gid_by_url={url:0})
        self.assertEqual(private['hits_displayed'],1)
        self.assertEqual(private['private_hits'][0]['original_physical_row'],41)
        self.assertEqual(private['private_hits'][0]['original_row_url'],
                         url+'#gid=0&range=A41:O41')
        self.assertFalse(private['user_identity_verified_by_this_function'])

    def test_reject_missing_duplicated_extra_and_swapped_response(self):
        plan=plan_supplier_sheet_reads(supplier_query='架空の仕入先A',
                                      approved_tab_metadata=[entry(row_count=79)])
        correct=fake_connector_responses(plan)
        failures=[correct[:-1],correct+[deepcopy(correct[1])]]
        altered=deepcopy(correct)
        altered[1]['sheet_name']='別タブ'
        failures.append(altered)
        altered=deepcopy(correct)
        altered[1]['requested_range']='A42:O79'
        failures.append(altered)
        altered=deepcopy(correct)
        altered[1]['spreadsheet_id']=FILE_B
        failures.append(altered)
        for bad in failures:
            with self.subTest(bad_count=len(bad)),self.assertRaises(ValueError):
                build_private_page_manifest(plan=plan,
                                            connector_responses=bad)

    def test_reject_header_incomplete_and_oversize_response(self):
        plan=plan_supplier_sheet_reads(supplier_query='架空の仕入先A',
                                      approved_tab_metadata=[entry(row_count=79)])
        bad=deepcopy(fake_connector_responses(plan))
        bad[0]['rows']=[]
        with self.assertRaisesRegex(ValueError,'header'):
            build_private_page_manifest(plan=plan,connector_responses=bad)
        bad=deepcopy(fake_connector_responses(plan))
        bad[1]['rows'].append(['架空の余分な行'])
        with self.assertRaisesRegex(ValueError,'extra rows'):
            build_private_page_manifest(plan=plan,connector_responses=bad)

    def test_reject_untrusted_rows_and_unknown_response_keys(self):
        plan=plan_supplier_sheet_reads(supplier_query='架空の仕入先A',
                                      approved_tab_metadata=[entry(row_count=40)])
        cases=[]
        b=deepcopy(fake_connector_responses(plan))
        b[1]['rows'][0][0]={'secret':'value'}
        cases.append(b)
        b=deepcopy(fake_connector_responses(plan))
        b[1]['rows'][0][0]='='+'A'*4001
        cases.append(b)
        b=deepcopy(fake_connector_responses(plan))
        b[1]['oauth_token']='not-allowed'
        cases.append(b)
        for changed in cases:
            with self.assertRaises(ValueError):
                build_private_page_manifest(plan=plan,
                                            connector_responses=changed)

    def test_private_plan_is_not_public_summary(self):
        plan=plan_supplier_sheet_reads(supplier_query='架空の仕入先A',
                                      approved_tab_metadata=[entry(row_count=998)])
        public=summarize_plan_without_private_sources(plan)
        dumped=json.dumps(public,ensure_ascii=False)
        for needle in (FILE_A,'架空の仕入先A','見積もり','A41:O79',
                       'SYNTHETIC'):
            self.assertNotIn(needle,dumped)
        self.assertEqual(public['selected_source_tabs'],1)
        self.assertEqual(public['planned_page_reads'],5)
        self.assertEqual(public['planned_header_reads'],1)
        self.assertTrue(public['unread_grid_rows_remain'])
        self.assertFalse(public['all_supplier_folders_searched'])

    def test_grid_row_count_is_not_content_completeness_proof(self):
        plan=plan_supplier_sheet_reads(supplier_query='架空の仕入先A',
                                      approved_tab_metadata=[entry(row_count=40)])
        public=summarize_plan_without_private_sources(plan)
        self.assertFalse(public['unread_grid_rows_remain'])
        self.assertFalse(public['all_product_rows_verified'])

    def test_empty_trailing_values_get_padded_and_never_claim_total_absence(self):
        plan=plan_supplier_sheet_reads(supplier_query='架空の仕入先A',
                                      approved_tab_metadata=[entry(row_count=79)])
        raw=fake_connector_responses(plan)
        raw[-1]['rows']=[]
        paged=build_private_page_manifest(plan=plan,connector_responses=raw)
        result=inspect_selected_connector_sheet_pages(
            manifest=paged,search={'field':'jan','query':JAN})
        self.assertEqual(result['public_search_summary']['hits_returned'],0)
        self.assertEqual(result['public_summary']
                         ['trailing_rows_unpopulated_in_connector_response'],39)
        self.assertFalse(result['public_summary']['all_rows_in_selected_tabs_searched'])

    def test_source_meta_or_connector_response_not_modified(self):
        meta=[entry(row_count=79)]
        before=deepcopy(meta)
        plan=plan_supplier_sheet_reads(supplier_query='架空の仕入先A',
                                      approved_tab_metadata=meta)
        original=deepcopy(plan)
        responses=fake_connector_responses(plan)
        source=deepcopy(responses)
        build_private_page_manifest(plan=plan,connector_responses=responses)
        self.assertEqual(meta,before)
        self.assertEqual(plan,original)
        self.assertEqual(responses,source)


if __name__=='__main__':
    unittest.main()
