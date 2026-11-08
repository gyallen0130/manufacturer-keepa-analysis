"""Offline metadata-only Drive inventory tests; no account, tokens or real IDs."""
import json
import unittest
from unittest.mock import Mock

from supplier_docs.drive_delta import (
    SCHEMA_VERSION, scan_approved_folder, plan_changed_files,
    scan_explicit_folder_set, plan_explicit_folder_set,
)

ROOT = 'fake_folder_123456'
DOC_A = 'fake_doc_abcdef123'
DOC_B = 'fake_doc_uvwxyz987'
DOC_C = 'fake_doc_klmnop456'


def file_meta(file_id, *, version='1', mime='application/vnd.google-apps.spreadsheet',
              modified='2026-01-01T00:00:00Z'):
    return {
        'id': file_id,
        'mimeType': mime,
        'version': version,
        'modifiedTime': modified,
        'parents': [ROOT],
        'trashed': False,
        'name': 'SECRET_NOT_REQUESTED',
    }


def fake_drive(*pages):
    service = Mock()
    service.files.return_value.list.return_value.execute.side_effect = list(pages)
    return service


def snapshot(files, folder_id=ROOT):
    return {
        'schema_version': SCHEMA_VERSION, 'folder_id': folder_id,
        'files': files, 'total_items': len(files),
        'unsupported_items': 0, 'unscanned_subfolders': 0,
    }


class DriveDeltaTests(unittest.TestCase):

    def test_scan_one_folder_with_pagination_and_without_sensitive_fields(self):
        service = fake_drive(
            {'files': [
                file_meta(DOC_A),
                file_meta('fake_subfolder_123', mime='application/vnd.google-apps.folder'),
            ], 'nextPageToken': 'private_token_one'},
            {'files': [
                file_meta(DOC_B, version='2'),
                file_meta('fake_image_123456', mime='image/jpeg'),
            ]},
        )
        result = scan_approved_folder(service, folder_id=ROOT)
        self.assertEqual(result['total_items'], 4)
        self.assertEqual(result['unsupported_items'], 1)
        self.assertEqual(result['unscanned_subfolders'], 1)
        self.assertEqual(set(result['files']), {DOC_A, DOC_B})
        call1 = service.files.return_value.list.call_args_list[0].kwargs
        call2 = service.files.return_value.list.call_args_list[1].kwargs
        self.assertEqual(call1['q'], "'" + ROOT + "' in parents and trashed = false")
        self.assertNotIn('name', call1['fields'])
        self.assertNotIn('permissions', call1['fields'])
        self.assertNotIn('pageToken', call1)
        self.assertEqual(call2['pageToken'], 'private_token_one')
        self.assertEqual(service.files.return_value.list.call_count, 2)
        service.files.return_value.update.assert_not_called()
        service.files.return_value.delete.assert_not_called()

    def test_first_scan_is_baseline_without_reprocessing(self):
        now = snapshot({DOC_A: {'mime_type': 'application/vnd.google-apps.spreadsheet',
                                'version': '10', 'modified_time': ''}})
        plan = plan_changed_files(None, now)
        self.assertEqual(plan['candidate_file_ids'], [])
        self.assertTrue(plan['is_baseline'])
        self.assertEqual(plan['summary']['baseline_count'], 1)
        self.assertNotIn(DOC_A, json.dumps(plan['summary']))

    def test_only_new_and_modified_candidates_and_missing_is_not_deletion(self):
        f = lambda version: {
            'mime_type': 'application/vnd.google-apps.spreadsheet',
            'version': version, 'modified_time': '2026-01-01T00:00:00Z'}
        before = snapshot({DOC_A: f('1'), DOC_B: f('2')})
        after = snapshot({DOC_A: f('3'), DOC_C: f('1')})
        plan = plan_changed_files(before, after)
        self.assertEqual(plan['candidate_file_ids'], [DOC_C, DOC_A])
        self.assertEqual(plan['unavailable_file_ids'], [DOC_B])
        self.assertEqual(plan['summary']['new'], 1)
        self.assertEqual(plan['summary']['changed'], 1)
        self.assertEqual(plan['summary']['unavailable_needs_review'], 1)
        self.assertNotIn('deleted', json.dumps(plan))
        for private_id in (DOC_A, DOC_B, DOC_C):
            self.assertNotIn(private_id, json.dumps(plan['summary']))

    def test_unchanged_files_are_not_requeued(self):
        f = {'mime_type': 'application/vnd.google-apps.spreadsheet',
             'version': '', 'modified_time': '2026-01-01T00:00:00Z'}
        before = snapshot({DOC_A: f})
        after = snapshot({DOC_A: dict(f)})
        result = plan_changed_files(before, after)
        self.assertEqual(result['candidate_file_ids'], [])
        self.assertEqual(result['summary']['unchanged'], 1)

    def test_incomplete_search_refused(self):
        service = fake_drive({'files': [file_meta(DOC_A)], 'incompleteSearch': True})
        with self.assertRaises(ValueError):
            scan_approved_folder(service, folder_id=ROOT)

    def test_duplicate_ids_refused_across_pages(self):
        service = fake_drive(
            {'files': [file_meta(DOC_A)], 'nextPageToken': 'token_1'},
            {'files': [file_meta(DOC_A)]},
        )
        with self.assertRaises(ValueError):
            scan_approved_folder(service, folder_id=ROOT)

    def test_missing_parent_and_invalid_revision_refused(self):
        for bad in [
            {'files': [{**file_meta(DOC_A), 'parents': ['somewhere_else_123']}]},
            {'files': [{**file_meta(DOC_A), 'version': 'secret-not-a-number'}]},
            {'files': [{**file_meta(DOC_A), 'modifiedTime': None, 'version': None}]},
            {'files': [{**file_meta(DOC_A), 'trashed': True}]},
        ]:
            with self.subTest(bad=bad):
                service = fake_drive(bad)
                with self.assertRaises(ValueError):
                    scan_approved_folder(service, folder_id=ROOT)

    def test_repeated_token_or_page_limit_rejected(self):
        repeated = fake_drive(
            {'files': [], 'nextPageToken': 'token_1'},
            {'files': [], 'nextPageToken': 'token_1'},
        )
        with self.assertRaises(ValueError):
            scan_approved_folder(repeated, folder_id=ROOT)
        too_many_pages = fake_drive(
            {'files': [], 'nextPageToken': 'token_2'})
        with self.assertRaises(ValueError):
            scan_approved_folder(too_many_pages, folder_id=ROOT, max_pages=1)

    def test_item_limit_refused(self):
        service = fake_drive({'files': [file_meta(DOC_A), file_meta(DOC_B)]})
        with self.assertRaises(ValueError):
            scan_approved_folder(service, folder_id=ROOT, max_items=1)

    def test_folder_id_injection_and_bound_values_rejected_before_request(self):
        service = Mock()
        for folder in ["", "abc' OR trashed = true", "short", None]:
            with self.assertRaises(ValueError):
                scan_approved_folder(service, folder_id=folder)
        with self.assertRaises(ValueError):
            scan_approved_folder(service, folder_id=ROOT, max_items=0)
        service.files.assert_not_called()

    def test_explicit_folder_set_only_visits_approved_folders(self):
        other = 'approved_folder_987654'
        second = {**file_meta(DOC_B, version='3'), 'parents': [other]}
        service = fake_drive(
            {'files': [file_meta(DOC_A)]},
            {'files': [second]},
        )
        snapshots = scan_explicit_folder_set(
            service, folder_ids=[ROOT, other], max_total_items=10)
        self.assertEqual(set(snapshots), {ROOT, other})
        self.assertEqual(snapshots[ROOT]['pages_scanned'], 1)
        calls = service.files.return_value.list.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertIn(ROOT, calls[0].kwargs['q'])
        self.assertIn(other, calls[1].kwargs['q'])
        self.assertNotIn('name', calls[1].kwargs['fields'])
        baseline = plan_explicit_folder_set(None, snapshots)
        self.assertTrue(baseline['is_baseline'])
        self.assertEqual(baseline['summary']['baseline_count'], 2)
        self.assertEqual(baseline['candidate_locations'], [])
        self.assertNotIn(ROOT, json.dumps(baseline['summary']))

    def test_batch_changes_and_missing_folder_require_review(self):
        other = 'approved_folder_987654'
        doc = lambda version: {
            'mime_type': 'application/vnd.google-apps.spreadsheet',
            'version': version, 'modified_time': ''}
        before = {ROOT: snapshot({DOC_A: doc('1')}),
                  other: snapshot({DOC_B: doc('1')}, folder_id=other)}
        after = {ROOT: snapshot({DOC_A: doc('2'), DOC_C: doc('1')}),
                 other: snapshot({}, folder_id=other)}
        plan = plan_explicit_folder_set(before, after)
        self.assertEqual(plan['summary']['new'], 1)
        self.assertEqual(plan['summary']['changed'], 1)
        self.assertEqual(plan['summary']['unavailable_needs_review'], 1)
        self.assertIn((ROOT, DOC_A), plan['candidate_locations'])
        self.assertIn((ROOT, DOC_C), plan['candidate_locations'])
        self.assertIn((other, DOC_B), plan['unavailable_locations'])
        with self.assertRaises(ValueError):
            plan_explicit_folder_set(before, {ROOT: after[ROOT]})

    def test_batch_rejects_duplicate_approved_folders_without_network(self):
        service = Mock()
        with self.assertRaises(ValueError):
            scan_explicit_folder_set(service, folder_ids=[ROOT, ROOT])
        service.files.assert_not_called()

    def test_batch_fails_closed_when_second_folder_cannot_be_fully_scanned(self):
        other = 'approved_folder_987654'
        service = fake_drive(
            {'files': [file_meta(DOC_A)]},
            {'files': [], 'nextPageToken': 'continued'},
        )
        with self.assertRaises(ValueError):
            scan_explicit_folder_set(
                service, folder_ids=[ROOT, other], max_total_pages=2)
        self.assertEqual(service.files.return_value.list.call_count, 2)

    def test_snapshot_mismatch_and_corruption_refused(self):
        good = snapshot({DOC_A: {
            'mime_type': 'application/vnd.google-apps.spreadsheet',
            'version': '1', 'modified_time': ''}})
        other = snapshot({}, folder_id='other_folder_1234')
        with self.assertRaises(ValueError):
            plan_changed_files(other, good)
        with self.assertRaises(ValueError):
            plan_changed_files(None, snapshot({
                DOC_A: {'mime_type': 'application/vnd.google-apps.spreadsheet',
                        'version': '', 'modified_time': ''}}))

    def test_missing_files_are_review_only_even_when_current_empty(self):
        previous = snapshot({DOC_A: {
            'mime_type': 'application/vnd.google-apps.spreadsheet',
            'version': '1', 'modified_time': ''}})
        plan = plan_changed_files(previous, snapshot({}))
        self.assertEqual(plan['candidate_file_ids'], [])
        self.assertEqual(plan['unavailable_file_ids'], [DOC_A])
        self.assertEqual(plan['summary']['unavailable_needs_review'], 1)


if __name__ == '__main__':
    unittest.main()
