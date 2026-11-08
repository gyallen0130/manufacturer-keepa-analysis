"""No-network tests for the encrypted PRIVATE repo checkpoint adapter.

Every user ID, repository and revision is synthetic. Uses an injected fake
GitHub session; no token, live HTTP, workflow, Google Drive or extra service.
"""
import base64
from datetime import datetime, timezone
import hashlib
import json
import unittest

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from supplier_docs.drive_delta import SCHEMA_VERSION
from supplier_docs.offline_review import issue_offline_ed25519_receipt
from supplier_docs.private_github_state import (
    PrivateGithubCheckpoint, BRANCH, PATH, API,
)

REPO = 'fake-owner/supplier-private-repo'
FOLDER = 'fake_folder_abcdefgh123'
DOC = 'fake_sheet_abcdefgh123'
NEW = 'fake_sheet_newxyz1234'
MIME = 'application/vnd.google-apps.spreadsheet'
KEY_ID = 'fake_reviewer_01'
WHEN = datetime(2026, 1, 1, tzinfo=timezone.utc)


def inventory(revisions):
    return {FOLDER: {
        'schema_version': SCHEMA_VERSION, 'folder_id': FOLDER,
        'files': {name: {'mime_type': MIME, 'version': version,
                         'modified_time': ''}
                  for name, version in revisions.items()},
        'total_items': len(revisions), 'pages_scanned': 1,
        'unsupported_items': 0, 'unscanned_subfolders': 0,
    }}


class FakeResponse:
    def __init__(self, status, value):
        self.status_code = status
        self._value = value

    def json(self):
        return self._value


class FakePrivateGithub:
    def __init__(self):
        self.private = True
        self.archived = False
        self.branch_exists = True
        self.file = None
        self.sha = None
        self.gets = []
        self.puts = []
        self.simulate_race = False

    @staticmethod
    def hash_blob(data):
        return hashlib.sha1(
            b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()

    def get(self, url, *, headers, params, timeout, allow_redirects):
        self.gets.append((url, params))
        assert url.startswith(API + '/repos/' + REPO)
        assert allow_redirects is False and timeout <= 30
        if url == API + '/repos/' + REPO:
            return FakeResponse(200, {
                'full_name': REPO, 'private': self.private,
                'archived': self.archived,
            })
        if url.endswith('/branches/' + BRANCH):
            return FakeResponse(
                200 if self.branch_exists else 404,
                {'name': BRANCH} if self.branch_exists else {})
        if url.endswith('/contents/' + PATH):
            assert params == {'ref': BRANCH}
            if self.file is None:
                return FakeResponse(404, {})
            return FakeResponse(200, {
                'type': 'file', 'path': PATH, 'encoding': 'base64',
                'sha': self.sha, 'size': len(self.file),
                'content': base64.b64encode(self.file).decode('ascii'),
            })
        raise RuntimeError('unexpected test URL')

    def put(self, url, *, headers, json, timeout, allow_redirects):
        assert url == API + '/repos/' + REPO + '/contents/' + PATH
        assert allow_redirects is False and json['branch'] == BRANCH
        assert timeout <= 30
        if self.simulate_race:
            return FakeResponse(409, {'message': 'private file was changed'})
        if self.file is None:
            if 'sha' in json:
                return FakeResponse(409, {})
        elif json.get('sha') != self.sha:
            return FakeResponse(409, {})
        body = base64.b64decode(json['content'])
        previous = self.file
        self.puts.append(json)
        self.file = body
        self.sha = self.hash_blob(body)
        return FakeResponse(
            201 if previous is None else 200,
            {'content': {'sha': self.sha}})


class PrivateGithubStateTests(unittest.TestCase):
    def setUp(self):
        self.session = FakePrivateGithub()
        self.store = PrivateGithubCheckpoint(self.session, repository=REPO)
        self.key = Fernet.generate_key()
        self.old = inventory({DOC: '1'})
        self.new = inventory({DOC: '2', NEW: '1'})
        self.reviewer_key = Ed25519PrivateKey.generate()
        self.trusted = {KEY_ID: self.reviewer_key.public_key()}

    def receipt(self, file_id):
        return issue_offline_ed25519_receipt(
            self.old, self.new, folder_id=FOLDER,
            file_id=file_id, event='changed',
            reviewer_id=KEY_ID, evidence_ref='fake_evidence_abcdef123',
            private_key=self.reviewer_key, reviewed_at=WHEN)

    def bootstrap(self):
        return self.store.initialize(
            key=self.key, approved_first_snapshot=self.old,
            approve_initial_baseline=True)

    def test_construction_never_connects_or_creates_state(self):
        self.assertEqual(len(self.session.gets), 0)
        self.assertEqual(len(self.session.puts), 0)
        for name in ('public-owner/..', '../unsafe', 'not-a-repo',
                     'one repo/two', '', 'owner/owner/path'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                PrivateGithubCheckpoint(self.session, repository=name)

    def test_missing_checkpoint_and_unapproved_first_baseline_refused(self):
        with self.assertRaises(FileNotFoundError):
            self.store.read(key=self.key)
        self.assertEqual(len(self.session.puts), 0)
        with self.assertRaises(ValueError):
            self.store.initialize(key=self.key,
                                  approved_first_snapshot=self.old)
        self.assertEqual(len(self.session.puts), 0)

    def test_initial_checkpoint_is_private_encrypted_and_create_once(self):
        first_sha = self.bootstrap()
        self.assertEqual(len(first_sha), 40)
        self.assertNotIn(DOC.encode(), self.session.file)
        self.assertNotIn(FOLDER.encode(), self.session.file)
        result, read_sha = self.store.read(key=self.key)
        self.assertEqual(result, self.old)
        self.assertEqual(read_sha, first_sha)
        self.assertEqual(len(self.session.puts), 1)
        self.assertNotIn('sha', self.session.puts[0])
        self.assertEqual(self.session.puts[0]['branch'], BRANCH)
        with self.assertRaises(FileExistsError):
            self.bootstrap()
        self.assertEqual(len(self.session.puts), 1)

    def test_repo_must_be_private_not_archived_and_branch_must_exist(self):
        for key, value in (
                ('private', False), ('archived', True),
                ('branch_exists', False)):
            self.session = FakePrivateGithub()
            setattr(self.session, key, value)
            self.store = PrivateGithubCheckpoint(self.session, repository=REPO)
            with self.subTest(key=key), self.assertRaises(PermissionError):
                self.bootstrap()
            self.assertEqual(len(self.session.puts), 0)

    def test_corruption_and_wrong_key_fail_closed(self):
        self.bootstrap()
        with self.assertRaises(ValueError):
            self.store.read(key=Fernet.generate_key())
        self.session.file = b'corrupted encrypted data'
        self.session.sha = self.session.hash_blob(self.session.file)
        with self.assertRaises(ValueError):
            self.store.read(key=self.key)
        self.assertEqual(len(self.session.puts), 1)

    def test_all_review_receipts_required_before_write(self):
        old_sha = self.bootstrap()
        with self.assertRaises(ValueError):
            self.store.advance_after_review(
                key=self.key, expected_sha=old_sha,
                current_snapshot=self.new, receipts=[self.receipt(DOC)],
                trusted_public_keys=self.trusted)
        self.assertEqual(len(self.session.puts), 1)
        result = self.store.advance_after_review(
            key=self.key, expected_sha=old_sha,
            current_snapshot=self.new,
            receipts=[self.receipt(DOC), self.receipt(NEW)],
            trusted_public_keys=self.trusted)
        self.assertTrue(result['written'])
        self.assertNotEqual(result['new_blob_sha'], old_sha)
        new_state, sha = self.store.read(key=self.key)
        self.assertEqual(new_state, self.new)
        self.assertEqual(sha, result['new_blob_sha'])
        self.assertEqual(self.session.puts[-1]['sha'], old_sha)

    def test_stale_revision_or_concurrent_put_stops(self):
        original_sha = self.bootstrap()
        self.session.simulate_race = True
        with self.assertRaises(RuntimeError):
            self.store.advance_after_review(
                key=self.key, expected_sha=original_sha,
                current_snapshot=self.new,
                receipts=[self.receipt(DOC), self.receipt(NEW)],
                trusted_public_keys=self.trusted)
        self.session.simulate_race = False
        self.assertEqual(len(self.session.puts), 1)
        self.store.advance_after_review(
            key=self.key, expected_sha=original_sha,
            current_snapshot=self.new,
            receipts=[self.receipt(DOC), self.receipt(NEW)],
            trusted_public_keys=self.trusted)
        with self.assertRaises(ValueError):
            self.store.advance_after_review(
                key=self.key, expected_sha=original_sha,
                current_snapshot=self.new, receipts=[],
                trusted_public_keys=self.trusted)
        self.assertEqual(len(self.session.puts), 2)

    def test_unchanged_revision_no_write(self):
        original_sha = self.bootstrap()
        result = self.store.advance_after_review(
            key=self.key, expected_sha=original_sha,
            current_snapshot=self.old, receipts=[],
            trusted_public_keys=self.trusted)
        self.assertEqual(result, {'written': False, 'unchanged': True})
        self.assertEqual(len(self.session.puts), 1)

    def test_forged_signatures_and_replay_blocked(self):
        old_sha = self.bootstrap()
        tampered = {**self.receipt(DOC),
                    'evidence_ref': 'fake_evidence_modified'}
        with self.assertRaises(ValueError):
            self.store.advance_after_review(
                key=self.key, expected_sha=old_sha,
                current_snapshot=self.new,
                receipts=[tampered, self.receipt(NEW)],
                trusted_public_keys=self.trusted)
        self.assertEqual(len(self.session.puts), 1)

    def test_read_json_failures_do_not_echo_ids_and_no_write(self):
        self.bootstrap()
        self.session.sha = 'not-a-real-sha'
        with self.assertRaises(ValueError) as ex:
            self.store.read(key=self.key)
        self.assertNotIn(DOC, str(ex.exception))
        self.assertEqual(len(self.session.puts), 1)

    def test_unknown_network_failure_is_redacted(self):
        class Broken:
            def get(self, *args, **kwargs):
                raise RuntimeError('private token and file ID leaked')
            def put(self, *args, **kwargs):
                raise RuntimeError('private token')
        broken = PrivateGithubCheckpoint(Broken(), repository=REPO)
        with self.assertRaises(RuntimeError) as ex:
            broken.read(key=self.key)
        self.assertNotIn('private token', str(ex.exception))
        self.assertNotIn('file ID leaked', str(ex.exception))


if __name__ == '__main__':
    unittest.main()
