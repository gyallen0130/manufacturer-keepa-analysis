"""Synthetic-only manual multi-row header mapping; no real quote data."""
import copy
import json
import unittest

from supplier_docs.header_layout_guard import inspect_header_layout
from supplier_docs.multi_source_readonly import (
    normalize_selected_sources, search_selected_sources)
from supplier_docs.tiered_header_mapping import (
    MAPPING_VERSION, map_explicit_tiered_headers,
    validate_tiered_mapping_schema)


JAN = '0000000000017'
ASIN = 'B0TEST0001'


def tiered_source():
    return {
        'source_file_id': 'FAKE_TIERED_VENDOR_001',
        'source_sheet': '架空商品リスト',
        'document_type': 'quote_response',
        'source_url': 'https://example.invalid/private',
        'rows': [
            [],
            ['商品名', '', '', ''],
            ['', 'JAN', '', ''],
            ['', '', '価格', ''],
            ['架空マスク', JAN, '99999', 'PRIVATE_EXTRA'],
            ['架空別商品', 100000000017, '=42*100', 'SECRET'],
        ],
    }


def mapping():
    return {
        'version': MAPPING_VERSION,
        'header_rows': [2, 3, 4],
        'data_start_row': 5,
        'fields': {
            'product_name_raw': {'row': 2, 'column': 1},
            'jan_string': {'row': 3, 'column': 2},
        },
    }


class TieredHeaderMappingTests(unittest.TestCase):
    def test_detects_multi_tier_before_manual_mapping(self):
        source = tiered_source()
        self.assertEqual(inspect_header_layout(source['rows'])['status'],
                         'multi_row_needs_review')
        without = normalize_selected_sources([source])
        self.assertEqual(without['public_summary']
                         ['source_status_counts']['needs_review'], 1)
        self.assertEqual(without['public_summary']['record_count'], 0)

    def test_explicit_evidence_yields_review_only_search_candidates(self):
        source = tiered_source()
        source['tiered_mapping'] = mapping()
        result = normalize_selected_sources([source])
        summary = result['public_summary']
        self.assertEqual(summary['source_status_counts']['mapped_review'], 1)
        self.assertFalse(summary['all_selected_windows_parsed'])
        self.assertEqual(summary['record_count'], 2)
        self.assertFalse(summary['profit_calculation_allowed'])
        doc = result['private_normalized_docs'][0]
        self.assertEqual(doc['header_rows'], [2, 3, 4])
        self.assertEqual(doc['mapped_header_cells']['jan_string'],
                         {'row': 3, 'column': 2})
        self.assertEqual([r['source_row'] for r in doc['records']], [5, 6])
        self.assertTrue(all(r['decision'] == 'needs_confirmation'
                            and not r['cost_present']
                            and not r['order_multiple']
                            for r in doc['records']))
        hit = search_selected_sources(result, field='jan', query=JAN)
        self.assertEqual(hit['public_summary']['hits_returned'], 1)
        self.assertEqual(hit['private_hits'][0]['source_row'], 5)
        self.assertEqual(hit['public_summary']
                         ['sources_with_review_only_candidates'], 1)
        self.assertEqual(hit['public_summary']['sources_not_searchable'], 0)

    def test_source_document_not_mutated(self):
        src = tiered_source()
        src['tiered_mapping'] = mapping()
        original = copy.deepcopy(src)
        normalize_selected_sources([src])
        self.assertEqual(src, original)

    def test_price_quantity_and_case_fields_never_mapped(self):
        for forbidden in ('cost_amount', 'order_multiple', 'tax', 'case_pack',
                          'source_profit_status'):
            m = mapping()
            m['fields'][forbidden] = {'row': 4, 'column': 3}
            with self.subTest(field=forbidden), self.assertRaises(ValueError):
                validate_tiered_mapping_schema(m)

    def test_stale_or_wrong_header_cell_is_rejected(self):
        src = tiered_source()
        src['tiered_mapping'] = mapping()
        src['rows'][2][1] = 'ASIN'  # Remains tiered, but mapped JAN cell changed.
        with self.assertRaisesRegex(ValueError, 'exact field label'):
            normalize_selected_sources([src])

    def test_combined_pos_itf_product_header_cannot_become_jan(self):
        lead_off = [[] for _ in range(15)]
        lead_off[11] = ['', '商品コード']
        lead_off[12] = ['', '', '', '', '商品名・POSコード・ITFコード']
        lead_off[13] = ['', '', '', '', '', '', '', '入数', '', '', '価格']
        lead_off[14] = ['', '', '', '', '', '', '', '', '', '価格']
        lead_off.append(['架空商品', '', '', '', '架空値'])
        src = {
            'source_file_id': 'FAKE_TIERED_VENDOR_001',
            'source_sheet': '階層リスト',
            'document_type': 'catalog', 'rows': lead_off,
            'tiered_mapping': {
                'version': MAPPING_VERSION,
                'header_rows': [12, 13, 14, 15],
                'data_start_row': 16,
                'fields': {'product_name_raw': {'row': 13, 'column': 5}},
            },
        }
        self.assertEqual(inspect_header_layout(lead_off)['status'],
                         'multi_row_needs_review')
        with self.assertRaisesRegex(ValueError, 'exact field label'):
            normalize_selected_sources([src])

    def test_disallow_same_column_for_two_identifiers(self):
        m = mapping()
        m['fields']['jan_string']['column'] = 1
        with self.assertRaises(ValueError):
            validate_tiered_mapping_schema(m)

    def test_reject_bool_bad_index_excess_rows_and_price_maps(self):
        bad = [
            ('header_rows', [2, True, 4]),
            ('header_rows', [2, 2, 4]),
            ('data_start_row', 4),
            ('data_start_row', 41),
            ('header_rows', [2, 3, 10]),
        ]
        for field, val in bad:
            m = mapping()
            m[field] = val
            with self.subTest(field=field, val=val), self.assertRaises(ValueError):
                validate_tiered_mapping_schema(m)

    def test_manual_mapping_cannot_override_normal_single_row(self):
        src = tiered_source()
        src['rows'] = [
            ['商品名', 'JAN', '単価'],
            ['架空マスク', JAN, '100'],
        ]
        src['tiered_mapping'] = mapping()
        with self.assertRaises(ValueError):
            normalize_selected_sources([src])

    def test_missing_data_window_rejected(self):
        src = tiered_source()
        src['rows'] = src['rows'][:4]
        src['tiered_mapping'] = mapping()
        with self.assertRaises(ValueError):
            normalize_selected_sources([src])

    def test_multi_supplier_mixed_parsed_and_review_and_unmapped(self):
        src = tiered_source()
        src['tiered_mapping'] = mapping()
        ordinary = {
            'source_file_id': 'FAKE_ORDINARY_VENDOR_002',
            'source_sheet': '見積',
            'document_type': 'quote_request',
            'rows': [['商品名', 'JAN', 'ASIN'],
                     ['架空テープ', JAN, ASIN]],
        }
        still_unmapped = tiered_source()
        still_unmapped['source_file_id'] = 'FAKE_UNMAPPED_VENDOR_003'
        result = normalize_selected_sources([src, ordinary, still_unmapped])
        counts = result['public_summary']['source_status_counts']
        self.assertEqual(counts['parsed'], 1)
        self.assertEqual(counts['mapped_review'], 1)
        self.assertEqual(counts['needs_review'], 1)
        hits = search_selected_sources(result, field='jan', query=JAN)
        self.assertEqual(hits['public_summary']['hits_returned'], 2)
        self.assertEqual(hits['public_summary']['sources_not_searchable'], 1)
        self.assertFalse(hits['public_summary']['product_identity_confirmed'])

    def test_headers_and_source_ids_never_echoed_in_public(self):
        src = tiered_source()
        src['tiered_mapping'] = mapping()
        v = normalize_selected_sources([src])
        h = search_selected_sources(v, field='jan', query=JAN)
        public = json.dumps([v['public_summary'], h['public_summary']],
                            ensure_ascii=False)
        for private in ('FAKE_TIERED_VENDOR_001', JAN, '架空マスク',
                        'PRIVATE_EXTRA', '99999', 'SECRET'):
            self.assertNotIn(private, public)
        self.assertEqual(v['public_summary']['source_writes'], 0)

    def test_no_price_calculation_even_if_price_column_is_visible(self):
        src = tiered_source()
        src['tiered_mapping'] = mapping()
        v = normalize_selected_sources([src])
        self.assertEqual(v['public_summary']['records_with_cost_field'], 0)
        self.assertTrue(all(r['cost_tax_mode'] == 'unknown'
                            for r in v['private_normalized_docs'][0]['records']))


if __name__ == '__main__':
    unittest.main()
