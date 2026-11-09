"""Fake-only, no-network tests for one encrypted private GitHub audit blob."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import unittest

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from supplier_docs.drive_delta import SCHEMA_VERSION
from supplier_docs.offline_review import issue_offline_ed25519_receipt
from supplier_docs.private_audit_bundle import (
    initialize_audit_bundle, propose_next_audit_bundle,
    verify_audit_bundle, MAX_HISTORY,
)
from supplier_docs.private_github_audit_checkpoint import PrivateGithubAuditCheckpoint
from supplier_docs.private_github_state import AUDIT_PATH, PATH, BRANCH

REPO = 'fake-owner/private-supplier-test'
FOLDER = 'fake_folder_review123'
A = 'fake_sheet_reviewabc123'
B = 'fake_sheet_reviewdef456'
UNAVAILABLE = 'fake_sheet_hidden456'
MIME = 'application/vnd.google-apps.spreadsheet'
WHO = 'reviewer_test_01'
WHEN = datetime(2026, 1, 3, tzinfo=timezone.utc)


def snapshot(files):
    return {FOLDER: {
        'schema_version': SCHEMA_VERSION, 'folder_id': FOLDER,
        'files': {i: {'mime_type': MIME, 'version': v,
                       'modified_time': ''} for i, v in files.items()},
        'total_items': len(files), 'pages_scanned': 1,
        'unsupported_items': 0, 'unscanned_subfolders': 0,
    }}


class Response:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self.body = body

    def json(self):
        return self.body


class FakeSession:
    def __init__(self):
        self.private = True
        self.active = True
        self.body = None
        self.sha = None
        self.put_calls = []
        self.reject_writes = False
        self.end = 'https://api.github.com/repos/' + REPO
        self.url = self.end + '/contents/' + AUDIT_PATH

    def get(self, url, *, headers, params, timeout, allow_redirects):
        assert allow_redirects is False
        if url == self.end:
            return Response(200, {'private': self.private,
                                  'archived': not self.active,
                                  'full_name': REPO})
        if url == self.end + '/branches/' + BRANCH:
            return Response(200, {'name': BRANCH})
        assert url == self.url
        assert params == {'ref': BRANCH}
        if self.body is None:
            return Response(404)
        return Response(200, {
            'type': 'file', 'path': AUDIT_PATH, 'encoding': 'base64',
            'size': len(self.body), 'sha': self.sha,
            'content': base64.b64encode(self.body).decode(),
        })

    def put(self, url, *, headers, json, timeout, allow_redirects):
        assert url == self.url
        assert allow_redirects is False and json['branch'] == BRANCH
        if self.reject_writes:
            return Response(409)
        old = self.body
        if (old is None and 'sha' in json) or (
                old is not None and json.get('sha') != self.sha):
            return Response(409)
        raw = base64.b64decode(json['content'], validate=True)
        self.put_calls.append(json)
        self.body = raw
        self.sha = hashlib.sha1(
            b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        return Response(201 if old is None else 200,
                        {'content': {'sha': self.sha}})


class PrivateAuditBundleTests(unittest.TestCase):
    def setUp(self):
        self.key = Fernet.generate_key()
        self.signer = Ed25519PrivateKey.generate()
        self.keys = {WHO: self.signer.public_key()}
        self.old = snapshot({A: '1', UNAVAILABLE: '1'})
        self.after = snapshot({A: '2', B: '1'})
        self.third = snapshot({A: '3', B: '1'})

    def receipt(self, previous, current, file_id, *, event='changed'):
        return issue_offline_ed25519_receipt(
            previous, current, folder_id=FOLDER, file_id=file_id,
            event=event, reviewer_id=WHO, evidence_ref='evidence_123456',
            private_key=self.signer, reviewed_at=WHEN)

    def all_receipts(self, previous=None, current=None):
        previous = self.old if previous is None else previous
        current = self.after if current is None else current
        return [self.receipt(previous, current, A),
                self.receipt(previous, current, B),
                self.receipt(previous, current, UNAVAILABLE,
                             event='unavailable')]

    def first_transition(self):
        base = initialize_audit_bundle(
            self.old, approve_initial_baseline=True)
        return propose_next_audit_bundle(
            base, self.after, receipts=self.all_receipts(),
            trusted_public_keys=self.keys)

    def test_initial_baseline_requires_explicit_acceptance(self):
        with self.assertRaises(ValueError):
            initialize_audit_bundle(self.old)
        base = initialize_audit_bundle(
            self.old, approve_initial_baseline=True)
        self.assertEqual(base['history'], [])
        checked = verify_audit_bundle(base, trusted_public_keys=self.keys)
        self.assertEqual(checked['private_current_snapshot'], self.old)
        self.assertFalse(checked['summary']['baseline_written'])

    def test_single_history_event_preserves_all_verifiable_signatures(self):
        bundle = self.first_transition()
        self.assertEqual(bundle['current_snapshot'], self.after)
        self.assertEqual(len(bundle['history']), 1)
        self.assertEqual(len(bundle['history'][0]['receipts']), 3)
        output = verify_audit_bundle(bundle, trusted_public_keys=self.keys)
        self.assertEqual(output['summary']['historical_review_cycles'], 1)
        self.assertNotIn(A, json.dumps(output['summary']))
        self.assertNotIn(WHO, json.dumps(output['summary']))

    def test_incomplete_or_forged_receipts_never_change_state(self):
        base = initialize_audit_bundle(
            self.old, approve_initial_baseline=True)
        with self.assertRaises(ValueError):
            propose_next_audit_bundle(
                base, self.after, receipts=self.all_receipts()[:2],
                trusted_public_keys=self.keys)
        forged = [{**self.all_receipts()[0], 'signature': '0' * 128},
                  *self.all_receipts()[1:]]
        with self.assertRaises(ValueError):
            propose_next_audit_bundle(
                base, self.after, receipts=forged,
                trusted_public_keys=self.keys)
        self.assertEqual(base['history'], [])
        self.assertEqual(base['current_snapshot'], self.old)

    def test_tampered_history_and_altered_current_state_fail_replay(self):
        bundle = self.first_transition()
        altered = dict(bundle)
        altered['current_snapshot'] = self.third
        with self.assertRaises(ValueError):
            verify_audit_bundle(altered, trusted_public_keys=self.keys)
        edited = {**bundle,
                  'history': [{**bundle['history'][0], 'receipts':
                               bundle['history'][0]['receipts'][:2]}]}
        with self.assertRaises(ValueError):
            verify_audit_bundle(edited, trusted_public_keys=self.keys)
        altered_chain = {**bundle,
                         'history': [{**bundle['history'][0],
                                      'previous_digest': '0' * 64}]}
        with self.assertRaises(ValueError):
            verify_audit_bundle(altered_chain, trusted_public_keys=self.keys)

    def test_public_key_rotation_without_archive_does_not_silently_pass(self):
        bundle = self.first_transition()
        other = {WHO: Ed25519PrivateKey.generate().public_key()}
        with self.assertRaises(ValueError):
            verify_audit_bundle(bundle, trusted_public_keys=other)

    def test_next_revision_replays_every_old_receipt(self):
        bundle = self.first_transition()
        second = propose_next_audit_bundle(
            bundle, self.third,
            receipts=[self.receipt(self.after, self.third, A)],
            trusted_public_keys=self.keys)
        self.assertEqual(len(second['history']), 2)
        self.assertEqual(second['history'][1]['sequence'], 2)
        self.assertEqual(
            verify_audit_bundle(second, trusted_public_keys=self.keys)
            ['private_current_snapshot'], self.third)

    def test_no_change_is_no_write_and_rejects_rogue_receipts(self):
        bundle = self.first_transition()
        self.assertIs(propose_next_audit_bundle(
            bundle, self.after, receipts=[], trusted_public_keys=self.keys),
            bundle)
        with self.assertRaises(ValueError):
            propose_next_audit_bundle(
                bundle, self.after, receipts=self.all_receipts(),
                trusted_public_keys=self.keys)

    def test_history_over_cap_is_denied(self):
        base = self.first_transition()
        oversized = {**base, 'history': base['history'] * (MAX_HISTORY + 1)}
        with self.assertRaises(ValueError):
            verify_audit_bundle(oversized, trusted_public_keys=self.keys)


class PrivateGithubAuditCheckpointTests(PrivateAuditBundleTests):
    def setUp(self):
        super().setUp()
        self.fake = FakeSession()
        self.remote = PrivateGithubAuditCheckpoint(self.fake, repository=REPO)

    def test_remote_starts_uninitialized_and_does_not_connect_on_construct(self):
        self.assertEqual(len(self.fake.put_calls), 0)
        with self.assertRaises(FileNotFoundError):
            self.remote.read(key=self.key, trusted_public_keys=self.keys)

    def initialize(self):
        return self.remote.initialize(
            key=self.key, first_snapshot=self.old,
            trusted_public_keys=self.keys, approve_initial_baseline=True)

    def advance(self, sha, receipts=None):
        return self.remote.advance_after_review(
            key=self.key, expected_sha=sha,
            current_snapshot=self.after,
            receipts=self.all_receipts() if receipts is None else receipts,
            trusted_public_keys=self.keys)

    def test_initialization_private_and_ciphertext_only(self):
        sha = self.initialize()
        self.assertEqual(len(sha), 40)
        self.assertNotIn(A.encode(), self.fake.body)
        self.assertNotIn(FOLDER.encode(), self.fake.body)
        self.assertEqual(self.fake.put_calls[0]['branch'], BRANCH)
        self.assertNotIn('sha', self.fake.put_calls[0])
        self.assertEqual(self.remote.read(
            key=self.key, trusted_public_keys=self.keys)['blob_sha'], sha)
        with self.assertRaises(FileExistsError):
            self.initialize()

    def test_one_conditional_write_commits_review_and_state_together(self):
        sha = self.initialize()
        result = self.advance(sha)
        self.assertTrue(result['written'])
        self.assertEqual(len(self.fake.put_calls), 2)
        after = self.remote.read(key=self.key, trusted_public_keys=self.keys)
        self.assertEqual(after['private_bundle']['current_snapshot'], self.after)
        self.assertEqual(len(after['private_bundle']['history']), 1)
        self.assertEqual(self.fake.put_calls[1]['sha'], sha)
        self.assertNotEqual(sha, after['blob_sha'])

    def test_crash_or_race_rejects_unverified_and_stale_writes(self):
        sha = self.initialize()
        with self.assertRaises(ValueError):
            self.advance(sha, receipts=self.all_receipts()[:1])
        self.assertEqual(len(self.fake.put_calls), 1)
        self.fake.reject_writes = True
        with self.assertRaises(RuntimeError):
            self.advance(sha)
        self.fake.reject_writes = False
        self.assertEqual(len(self.fake.put_calls), 1)
        self.advance(sha)
        with self.assertRaises(ValueError):
            self.advance(sha)
        self.assertEqual(len(self.fake.put_calls), 2)

    def test_unmodified_snapshot_does_not_write(self):
        sha = self.initialize()
        response = self.remote.advance_after_review(
            key=self.key, expected_sha=sha, current_snapshot=self.old,
            receipts=[], trusted_public_keys=self.keys)
        self.assertEqual(response, {'written': False, 'unchanged': True})
        self.assertEqual(len(self.fake.put_calls), 1)

    def test_wrong_key_private_requirement_or_tampered_history_fail(self):
        sha = self.initialize()
        with self.assertRaises(ValueError):
            self.remote.read(key=Fernet.generate_key(),
                             trusted_public_keys=self.keys)
        self.fake.private = False
        with self.assertRaises(PermissionError):
            self.remote.read(key=self.key, trusted_public_keys=self.keys)
        self.fake.private = True
        self.advance(sha)
        unsealed = json.loads(Fernet(self.key).decrypt(self.fake.body))
        unsealed['history'][0]['receipts'] = []
        self.fake.body = Fernet(self.key).encrypt(
            json.dumps(unsealed, ensure_ascii=False).encode())
        self.fake.sha = FakeSessionHash(self.fake.body)
        with self.assertRaises(ValueError):
            self.remote.read(key=self.key, trusted_public_keys=self.keys)

    def test_checkpoint_path_is_never_default_v1_path(self):
        self.assertTrue(self.fake.url.endswith('/' + AUDIT_PATH))
        self.assertFalse(self.fake.url.endswith('/' + PATH))


def FakeSessionHash(raw):
    return hashlib.sha1(
        b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


if __name__ == '__main__':
    unittest.main()
