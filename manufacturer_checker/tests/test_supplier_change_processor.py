"""Synthetic, offline tests for approved changed-Sheets handoff."""
import json
import unittest
from unittest.mock import Mock

from supplier_docs.change_processor import inspect_approved_sheet_changes
from supplier_docs.drive_delta import SCHEMA_VERSION
from supplier_docs.snapshot_store import finalize_inventory

FOLDER = 'fake_folder_abcdef1'
SHEET = 'fake_sheet_abcde123'
UNCHANGED = 'fake_sheet_unchanged1'
BINARY = 'fake_binary_abcde123'
SHEET_TWO = 'fake_sheet_twoxyz234'
NATIVE = 'application/vnd.google-apps.spreadsheet'
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def state(files):
    return {FOLDER: {
        'schema_version': SCHEMA_VERSION, 'folder_id': FOLDER,
        'files': {file_id: {
            'mime_type': mime, 'version': version, 'modified_time': ''}
            for file_id, (mime, version) in files.items()},
        'total_items': len(files), 'pages_scanned': 1,
        'unsupported_items': 0, 'unscanned_subfolders': 0,
    }}


def fake_service(*, tab_headers=None, failures=None):
    """No network. All source rows are invented."""
    tab_headers = tab_headers or {
        '表A': [['メーカー', '商品名', 'ASIN'],
               ['架空卸', '秘密商品A', 'B012345678']],
        '表B': [['メーカー', '商品名', '卸値', '卸値（税込）', 'ASIN'],
               ['架空卸', '秘密商品B', 1000, 1100, 'B098765432']],
    }
    api = Mock()
    api.spreadsheets.return_value.get.return_value.execute.return_value = {
        'sheets': [
            {'properties': {'title': tab, 'sheetType': 'GRID'}}
            for tab in tab_headers
        ]
    }
    def get_values(*, spreadsheetId, range, valueRenderOption):
        assert valueRenderOption == 'FORMULA'
        tab = range.split('!', 1)[0].strip("'")
        result = Mock()
        if failures and tab in failures:
            result.execute.side_effect = RuntimeError('synthetic read failed')
        else:
            result.execute.return_value = {'values': tab_headers[tab]}
        return result
    api.spreadsheets.return_value.values.return_value.get.side_effect = get_values
    return api


class ApprovedChangedSheetsTests(unittest.TestCase):
    def setUp(self):
        self.before = state({
            SHEET: (NATIVE, '1'), UNCHANGED: (NATIVE, '1')})
        self.current = state({
            SHEET: (NATIVE, '2'), UNCHANGED: (NATIVE, '1'),
            BINARY: (XLSX, '1')})
        self.manifest = {(FOLDER, SHEET): {
            '表A': 'quote_request', '表B': 'quote_request'}}

    def test_only_changed_approved_tabs_are_read_and_results_are_private(self):
        service = fake_service()
        output = inspect_approved_sheet_changes(
            service, previous=self.before, current=self.current,
            approved_targets=self.manifest)
        stats = output['summary']
        self.assertEqual(stats['candidate_files'], 2)
        self.assertEqual(stats['inspected_sheets'], 1)
        self.assertEqual(stats['pending_files'], 1)
        self.assertEqual(stats['candidate_rows'], 2)
        self.assertEqual(stats['warning_code_counts']['AMBIGUOUS_COLUMNS'], 1)
        self.assertEqual(stats['risk_counts']['ASIN_UNVERIFIED'], 2)
        self.assertFalse(output['baseline_advanced'])
        self.assertTrue(stats['requires_explicit_acknowledgement'])
        self.assertEqual(output['private_inspections'][0]['location'],
                         (FOLDER, SHEET))
        self.assertEqual(output['pending_locations'], [(FOLDER, BINARY)])
        all_public = json.dumps(stats, ensure_ascii=False)
        for private in (FOLDER, SHEET, BINARY, UNCHANGED,
                        '秘密商品A', '秘密商品B', '1000', '1100'):
            self.assertNotIn(private, all_public)
        client = service.spreadsheets.return_value
        self.assertEqual(client.get.call_count, 1)
        self.assertEqual(client.values.return_value.get.call_count, 2)
        client.values.return_value.update.assert_not_called()
        # This inspection is deliberately NOT a completion receipt.
        with self.assertRaises(ValueError):
            finalize_inventory(self.before, self.current)

    def test_empty_manifest_never_reads_any_candidate(self):
        service = Mock()
        output = inspect_approved_sheet_changes(
            service, previous=self.before, current=self.current,
            approved_targets={})
        self.assertEqual(output['summary']['pending_files'], 2)
        self.assertEqual(output['summary']['inspected_sheets'], 0)
        service.spreadsheets.assert_not_called()

    def test_baseline_requires_separate_approval_without_api_call(self):
        service = Mock()
        with self.assertRaises(ValueError):
            inspect_approved_sheet_changes(
                service, previous=None, current=self.current,
                approved_targets=self.manifest)
        service.spreadsheets.assert_not_called()

    def test_unchanged_or_binary_targets_fail_preflight(self):
        for bad in [
            {(FOLDER, UNCHANGED): {'表A': 'quote_request'}},
            {(FOLDER, BINARY): {'表A': 'quote_request'}},
            {(FOLDER, SHEET): {'表A': 'not-a-doc-type'}},
            {(FOLDER, SHEET): {'wrong!title': 'quote_request'}},
            {(FOLDER, SHEET): {}},
        ]:
            service = Mock()
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                inspect_approved_sheet_changes(
                    service, previous=self.before, current=self.current,
                    approved_targets=bad)
            service.spreadsheets.assert_not_called()

    def test_aggregate_cells_are_checked_before_any_api_call(self):
        after = state({SHEET: (NATIVE, '2'),
                       SHEET_TWO: (NATIVE, '1')})
        manifest = {
            (FOLDER, SHEET): {'表A': 'quote_request', '表B': 'quote_request'},
            (FOLDER, SHEET_TWO): {'表A': 'quote_request', '表B': 'quote_request'},
        }
        service = Mock()
        with self.assertRaises(ValueError):
            inspect_approved_sheet_changes(
                service, previous=state({SHEET: (NATIVE, '1')}),
                current=after, approved_targets=manifest,
                rows_per_tab=40, end_col='L', max_total_cells=1800)
        service.spreadsheets.assert_not_called()

    def test_hidden_or_missing_tab_fails_with_no_completion(self):
        service = fake_service(tab_headers={
            '表A': [['商品名'], ['架空商品']]})
        with self.assertRaises(ValueError):
            inspect_approved_sheet_changes(
                service, previous=self.before, current=self.current,
                approved_targets=self.manifest)
        self.assertEqual(service.spreadsheets.return_value.values.return_value.get.call_count, 0)

    def test_reader_exception_does_not_advance_baseline_or_return_partial(self):
        service = fake_service(failures={'表B'})
        with self.assertRaises(RuntimeError):
            inspect_approved_sheet_changes(
                service, previous=self.before, current=self.current,
                approved_targets=self.manifest)
        with self.assertRaises(ValueError):
            finalize_inventory(self.before, self.current)

    def test_ambiguous_price_is_not_promoted_into_auto_decision(self):
        result = inspect_approved_sheet_changes(
            fake_service(), previous=self.before, current=self.current,
            approved_targets=self.manifest)
        private = result['private_inspections'][0]
        self.assertTrue(private['tab_summaries'][1]['has_ambiguous_columns'])
        self.assertEqual(private['status'], 'inspection_requires_review')
        self.assertNotIn('completed_locations', result)

    def test_invalid_bounds_fail_before_network(self):
        bad_limits = [
            {'max_files': 0}, {'rows_per_tab': 1}, {'end_col': 'AA'},
            {'end_col': 'a'}, {'max_total_cells': 0},
            {'max_files': True}, {'rows_per_tab': True}
        ]
        for limit in bad_limits:
            service = Mock()
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                inspect_approved_sheet_changes(
                    service, previous=self.before, current=self.current,
                    approved_targets=self.manifest, **limit)
            service.spreadsheets.assert_not_called()


if __name__ == '__main__':
    unittest.main()
