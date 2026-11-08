"""Credential-free Windows/Linux tests of interactive encrypted backup entrypoint.

These tests invoke no real terminal, no paid service, no Google, no GitHub
authentication and no actual supplier data. Recovery keys are throwaway.
"""
import base64
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from supplier_docs.drive_delta import SCHEMA_VERSION
from supplier_docs.offline_review import issue_offline_ed25519_receipt
from supplier_docs.private_audit_bundle import (
    initialize_audit_bundle, propose_next_audit_bundle,
)
from supplier_docs.offline_recovery_archive import (
    _github_blob_sha, create_offline_recovery_archive,
)
from supplier_docs.local_backup_store import store_verified_local_backup
from supplier_docs.local_backup_cli import (
    SCHEMA, load_pinned_public_keys, make_parser,
    perform_local_operation, main,
)

FOLDER = 'fake_folder_interactive123'
SHEET = 'fake_sheet_interactive123'
WHO = 'fake_reviewer_interactive123'
MIME = 'application/vnd.google-apps.spreadsheet'


def snapshot(version):
    return {FOLDER: {
        'schema_version': SCHEMA_VERSION, 'folder_id': FOLDER,
        'files': {SHEET: {
            'mime_type': MIME, 'version': version,
            'modified_time': ''}},
        'total_items': 1, 'pages_scanned': 1,
        'unsupported_items': 0, 'unscanned_subfolders': 0,
    }}


class _FakeTTY(io.StringIO):
    def isatty(self):
        return True


class WindowsInteractiveBackupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.local = Path(temp.name, 'private')
        self.external = Path(temp.name, 'external-device-simulation')
        self.local.mkdir(mode=0o700)
        self.external.mkdir(mode=0o700)
        if os.name == 'posix':
            os.chmod(self.local, 0o700)
            os.chmod(self.external, 0o700)
        self.source = self.local / 'fake-signed-backup.enc'
        self.dest = self.external / 'fake-signed-backup-copy.enc'
        self.keyring = self.local / 'trusted-public-keys.json'
        signer = Ed25519PrivateKey.generate()
        self.trusted = {WHO: signer.public_key()}
        raw_public = signer.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        keyring_bytes = json.dumps({
            'schema_version': SCHEMA,
            'reviewers': {WHO: base64.b64encode(raw_public).decode('ascii')},
        }, sort_keys=True).encode('utf-8')
        self.keyring.write_bytes(keyring_bytes)
        self.fingerprint = hashlib.sha256(keyring_bytes).hexdigest()
        self.recovery = Fernet.generate_key()
        self.primary = Fernet.generate_key()
        original, newer = snapshot('1'), snapshot('2')
        receipt = issue_offline_ed25519_receipt(
            original, newer, folder_id=FOLDER, file_id=SHEET,
            event='changed', reviewer_id=WHO,
            evidence_ref='fake_evidence_interactive123',
            private_key=signer,
            reviewed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        bundle = propose_next_audit_bundle(
            initialize_audit_bundle(
                original, approve_initial_baseline=True),
            newer, receipts=[receipt], trusted_public_keys=self.trusted)
        cipher = Fernet(self.primary).encrypt(json.dumps(bundle).encode())
        self.archive = create_offline_recovery_archive(
            cipher, primary_key=self.primary, recovery_key=self.recovery,
            source_blob_sha=_github_blob_sha(cipher),
            trusted_public_keys=self.trusted)['private_encrypted_archive']

    def saved(self):
        return store_verified_local_backup(
            self.source, encrypted_archive=self.archive,
            recovery_key=self.recovery, trusted_public_keys=self.trusted,
            approve_new_backup=True, windows_storage_reviewed=True)

    def options(self, command='verify', **kwargs):
        arguments = [
            command, '--source', str(self.source),
            '--public-keyring', str(self.keyring),
            '--trusted-keyring-sha256', self.fingerprint,
        ]
        if command == 'copy':
            arguments += ['--destination', str(self.dest)]
        return make_parser().parse_args(arguments)

    @staticmethod
    def accept(prompt):
        return prompt.split('Type ', 1)[1].split(' to continue:', 1)[0]

    def perform(self, operation='verify', *, ask=None, secret=None):
        return perform_local_operation(
            self.options(operation),
            confirmation_reader=self.accept if ask is None else ask,
            secret_reader=(
                (lambda prompt: self.recovery.decode('ascii'))
                if secret is None else secret))

    def test_public_keyring_requires_separately_pinned_sha256(self):
        keys = load_pinned_public_keys(
            self.keyring, trusted_keyring_sha256=self.fingerprint)
        self.assertIn(WHO, keys)
        with self.assertRaises(ValueError):
            load_pinned_public_keys(
                self.keyring, trusted_keyring_sha256='0' * 64)
        self.assertNotIn(self.recovery, self.keyring.read_bytes())

    def test_modified_keyring_rejected_before_backup_access(self):
        self.saved()
        self.keyring.write_text('{"schema_version":"fake"}', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.perform()
        self.assertFalse(self.dest.exists())

    def test_verify_only_prints_counts_and_does_not_mutate_file(self):
        self.saved()
        before = self.source.read_bytes()
        output = self.perform()
        self.assertEqual(output, {
            'operation': 'verify', 'encrypted_backup_verified': True,
            'review_cycles_verified': 1, 'files_created': 0, 'api_calls': 0})
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse(self.dest.exists())
        private = json.dumps(output)
        for token in (FOLDER, SHEET, WHO, str(self.source)):
            self.assertNotIn(token, private)

    def test_unapproved_local_storage_is_refused(self):
        self.saved()
        prompts = []
        def deny(prompt):
            prompts.append(prompt)
            return 'NO'
        with self.assertRaises(PermissionError):
            self.perform(ask=deny)
        self.assertEqual(len(prompts), 1)

    def test_invalid_or_wrong_hidden_key_is_refused(self):
        self.saved()
        for val in ('', 'not-a-key', 'not-ASCII-🗝' * 4,
                    Fernet.generate_key().decode('ascii')):
            with self.subTest(kind=len(val)), self.assertRaises(ValueError):
                self.perform(secret=lambda prompt: val)

    def test_copy_requires_separate_device_and_confirmed_write(self):
        self.saved()
        def refuse_copy(prompt):
            if 'SEPARATE-DEVICE' in prompt:
                return 'NO'
            return self.accept(prompt)
        with self.assertRaises(PermissionError):
            self.perform('copy', ask=refuse_copy)
        self.assertFalse(self.dest.exists())

    def test_verified_copy_creates_ciphertext_only_and_never_overwrites(self):
        self.saved()
        result = self.perform('copy')
        self.assertEqual(result['operation'], 'copy')
        self.assertTrue(result['encrypted_copy_created'])
        self.assertFalse(result['device_independence_verified_by_code'])
        self.assertEqual(self.dest.read_bytes(), self.archive)
        with self.assertRaises(FileExistsError):
            self.perform('copy')
        self.assertEqual(self.dest.read_bytes(), self.archive)

    def test_no_backup_fails_without_copy_or_exposing_source(self):
        with self.assertRaises(FileNotFoundError):
            self.perform()
        self.assertFalse(self.dest.exists())

    def test_unrecognized_secret_flag_does_not_echo_sensitive_argument(self):
        buf = io.StringIO()
        arguments = [
            'verify', '--source', str(self.source),
            '--public-keyring', str(self.keyring),
            '--trusted-keyring-sha256', self.fingerprint,
            '--password', 'VERY_PRIVATE_SUPPLIER_KEY_123',
        ]
        with redirect_stderr(buf), self.assertRaises(SystemExit):
            make_parser().parse_args(arguments)
        self.assertNotIn('VERY_PRIVATE_SUPPLIER_KEY_123', buf.getvalue())
        self.assertIn('no secrets allowed', buf.getvalue())

    def test_noninteractive_terminal_refuses_before_key_read(self):
        got = []
        stderr = io.StringIO()
        argv = [
            'verify', '--source', str(self.source),
            '--public-keyring', str(self.keyring),
            '--trusted-keyring-sha256', self.fingerprint,
        ]
        status = main(
            argv, input_stream=io.StringIO(), error_stream=stderr,
            secret_reader=lambda prompt: got.append('called') or '')
        self.assertEqual(status, 2)
        self.assertEqual(got, [])
        self.assertIn('interactive terminal', stderr.getvalue())
        self.assertNotIn(str(self.source), stderr.getvalue())

    def test_interactive_cli_redacts_stdout_and_failure_details(self):
        self.saved()
        argv = [
            'verify', '--source', str(self.source),
            '--public-keyring', str(self.keyring),
            '--trusted-keyring-sha256', self.fingerprint,
        ]
        out, err = io.StringIO(), _FakeTTY()
        with redirect_stdout(out):
            status = main(argv, input_stream=_FakeTTY(), error_stream=err,
                          confirmation_reader=self.accept,
                          secret_reader=lambda prompt: self.recovery.decode())
        self.assertEqual(status, 0)
        summary = json.loads(out.getvalue())
        self.assertEqual(summary['review_cycles_verified'], 1)
        for sensitive in (WHO, SHEET, str(self.source), self.recovery.decode()):
            self.assertNotIn(sensitive, out.getvalue() + err.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            failure = main(
                argv, input_stream=_FakeTTY(), error_stream=err,
                confirmation_reader=self.accept,
                secret_reader=lambda prompt: Fernet.generate_key().decode())
        self.assertEqual(failure, 1)
        self.assertEqual(out.getvalue(), '')
        self.assertNotIn(str(self.source), err.getvalue())

    def test_subprocess_cannot_verify_secret_through_noninteractive_stdin(self):
        root = Path(__file__).resolve().parents[1]
        process = subprocess.run(
            [sys.executable, '-m', 'supplier_docs.local_backup_cli',
             'verify', '--source', str(self.source),
             '--public-keyring', str(self.keyring),
             '--trusted-keyring-sha256', self.fingerprint],
            input='DONT_READ_THIS_KEY\n', cwd=root,
            text=True, capture_output=True, timeout=15)
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stdout, '')
        self.assertNotIn('DONT_READ_THIS_KEY', process.stderr)
        self.assertNotIn(str(self.source), process.stderr)


if __name__ == '__main__':
    unittest.main()
