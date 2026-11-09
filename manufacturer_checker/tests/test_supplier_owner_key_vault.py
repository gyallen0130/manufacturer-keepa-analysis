"""Synthetic-only Windows/Linux tests: passphrase-encrypted owner key and decrypt.

No Google/real GitHub API, user key, supplier price, persistent key or cloud
service. Temporary X25519 keys and fake trade values are deleted after tests.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from contextlib import redirect_stderr

from cryptography.hazmat.primitives import serialization

from supplier_docs.owner_key_vault import (
    create_owner_key_vault, unlock_owner_private_key,
    read_owner_encrypted_artifact, export_owner_inspections,
)
from supplier_docs.owner_result_cli import parser, perform, main
from supplier_docs.private_result_envelope import seal_private_inspections

PASSWORD = 'Long synthetic vault passphrase for test 2026!'
SECRET = 'FAKE_SUPPLIER_CONFIDENTIAL_PRICE_1286'
FILE_ID = 'fake_owner_sheet_abcdefghijkl'
REPORT = {
    'public_summary': {'normalized_records': 1, 'approved_files': 1},
    'private_inspections': [
        {'spreadsheet_id': FILE_ID, 'tabs': [
            {'title': '見積書', 'status': 'parsed', 'records': [
                {'product_name_raw': 'FAKE Product Name',
                 'cost_amount': SECRET, 'jan_string': '0012345678901'}]}]},
    ],
}


class _FakeTTY(io.StringIO):
    def isatty(self):
        return True


class OwnerVaultTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.private_dir = self.root / 'vaults'
        self.private_dir.mkdir(mode=0o700)
        self.artifact_dir = self.root / 'downloads'
        self.artifact_dir.mkdir(mode=0o700)
        if os.name == 'posix':
            os.chmod(self.private_dir, 0o700)
            os.chmod(self.artifact_dir, 0o700)
        self.vault = self.private_dir / 'owner-private-key.vault'
        self.artifact = self.artifact_dir / 'owner-encrypted-result.json'
        self.output = self.private_dir / 'private-supplier-data.json'
        self.details = self.make_vault()
        self.build_artifact()

    def make_vault(self):
        return create_owner_key_vault(
            self.vault, passphrase=PASSWORD,
            approve_key_creation=True, windows_storage_reviewed=True)

    def build_artifact(self):
        encrypted = seal_private_inspections(
            REPORT,
            recipient_public_key_b64=self.details['public_key_b64'],
            trusted_fingerprint_sha256=self.details['fingerprint_sha256'])
        self.artifact.write_text(json.dumps(encrypted), encoding='utf-8')

    def read(self, **kw):
        args = dict(
            vault_path=self.vault, artifact_path=self.artifact,
            passphrase=PASSWORD,
            trusted_fingerprint_sha256=self.details['fingerprint_sha256'],
            windows_storage_reviewed=True)
        args.update(kw)
        return read_owner_encrypted_artifact(**args)

    def export(self, **kw):
        args = dict(
            vault_path=self.vault, artifact_path=self.artifact,
            output_path=self.output, passphrase=PASSWORD,
            trusted_fingerprint_sha256=self.details['fingerprint_sha256'],
            approve_plaintext_export=True,
            windows_storage_reviewed=True)
        args.update(kw)
        return export_owner_inspections(**args)

    def test_generated_private_key_never_stored_as_plaintext(self):
        raw = self.vault.read_bytes()
        self.assertNotIn(PASSWORD.encode(), raw)
        self.assertNotIn(SECRET.encode(), raw)
        self.assertNotIn(FILE_ID.encode(), raw)
        priv = unlock_owner_private_key(
            self.vault, passphrase=PASSWORD,
            trusted_fingerprint_sha256=self.details['fingerprint_sha256'],
            windows_storage_reviewed=True)
        secret = priv.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption())
        self.assertNotIn(secret, raw)
        self.assertTrue(self.details['vault_created'])
        self.assertFalse(self.details['private_key_printed'])
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(self.vault.stat().st_mode), 0o600)

    def test_decrypted_owner_report_matches_encrypted_original(self):
        self.assertEqual(self.read(), REPORT)
        self.assertFalse(self.output.exists())

    def test_wrong_password_wrong_pin_or_bad_password_length_denied(self):
        for kw in (
            {'passphrase': 'wrong long vault passphrase 12345'},
            {'passphrase': 'too short'},
            {'trusted_fingerprint_sha256': '0' * 64},
            {'trusted_fingerprint_sha256': 'not hex'},
        ):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.read(**kw)
        self.assertFalse(self.output.exists())

    def test_vault_tampering_or_scrypt_parameter_change_rejected(self):
        original = json.loads(self.vault.read_bytes())
        for field, mutation in (
            ('salt_b64', 'AAAAAAAAAAAAAAAAAAAAAA=='),
            ('nonce_b64', 'AAAAAAAAAAAAAAAA'),
            ('encrypted_private_key_b64', 'A' * 64),
            ('kdf', {'algorithm': 'scrypt', 'n': 2, 'r': 8, 'p': 1}),
        ):
            broken = dict(original)
            broken[field] = mutation
            self.vault.write_text(json.dumps(broken), encoding='utf-8')
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.read()
        self.vault.write_text(json.dumps(original), encoding='utf-8')

    def test_vault_create_once_does_not_replace_existing_key(self):
        original = self.vault.read_bytes()
        with self.assertRaises(FileExistsError):
            self.make_vault()
        self.assertEqual(original, self.vault.read_bytes())
        with self.assertRaises(ValueError):
            create_owner_key_vault(
                self.vault, passphrase=PASSWORD,
                windows_storage_reviewed=True)

    def test_corrupted_encrypted_result_not_exported(self):
        original = self.artifact.read_bytes()
        self.artifact.write_bytes(b'{"plain":"fake confidential"}')
        with self.assertRaises(ValueError):
            self.export()
        self.assertFalse(self.output.exists())
        self.artifact.write_bytes(original)
        wrong = json.loads(self.artifact.read_text())
        wrong['ciphertext_b64'] = '!!!!' + wrong['ciphertext_b64']
        self.artifact.write_text(json.dumps(wrong), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.read()
        self.assertFalse(self.output.exists())

    def test_export_requires_explicit_approval_and_never_overwrites(self):
        with self.assertRaises(ValueError):
            self.export(approve_plaintext_export=False)
        self.assertFalse(self.output.exists())
        summary = self.export()
        self.assertTrue(summary['plaintext_file_created'])
        self.assertFalse(summary['detail_rows_logged'])
        self.assertEqual(json.loads(self.output.read_text(encoding='utf-8')), REPORT)
        original = self.output.read_bytes()
        with self.assertRaises(FileExistsError):
            self.export()
        self.assertEqual(self.output.read_bytes(), original)
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)

    def test_private_folder_and_relative_path_rejected(self):
        with self.assertRaises(ValueError):
            self.export(output_path='relative-plaintext.json')
        with self.assertRaises(ValueError):
            self.export(output_path=self.root / 'missing' / 'export.json')
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(os.name == 'posix', 'POSIX owner mode validation')
    def test_insecure_parent_or_file_mode_rejected(self):
        os.chmod(self.private_dir, 0o755)
        with self.assertRaises(PermissionError):
            self.read()
        os.chmod(self.private_dir, 0o700)
        os.chmod(self.vault, 0o644)
        with self.assertRaises(PermissionError):
            self.read()

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink validation')
    def test_linked_vault_and_destination_rejected(self):
        shortcut = self.root / 'shortcut'
        shortcut.symlink_to(self.private_dir, target_is_directory=True)
        with self.assertRaises(PermissionError):
            self.read(vault_path=shortcut / self.vault.name)
        symlink = self.private_dir / 'linked-output.json'
        symlink.symlink_to(self.output)
        with self.assertRaises(FileExistsError):
            self.export(output_path=symlink)

    def test_never_decrypt_or_export_inside_git_working_tree(self):
        (self.root / '.git').mkdir()
        with self.assertRaises(PermissionError):
            self.read()
        with self.assertRaises(PermissionError):
            self.export()
        self.assertFalse(self.output.exists())

    def test_short_or_identical_passphrase_rejected_before_new_file(self):
        for pw in ('short', 'bad\x00long passphrase 1234'):
            dest = self.private_dir / 'new-vault.vault'
            with self.subTest(pw=pw), self.assertRaises(ValueError):
                create_owner_key_vault(
                    dest, passphrase=pw, approve_key_creation=True,
                    windows_storage_reviewed=True)
            self.assertFalse(dest.exists())


class OwnerCliTests(OwnerVaultTests):
    @staticmethod
    def confirm(prompt):
        return prompt.split('Type ', 1)[1].split(' to confirm:', 1)[0]

    def options(self, command='inspect'):
        args = [command, '--vault', str(self.vault)]
        if command in ('inspect', 'export'):
            args += ['--artifact', str(self.artifact),
                     '--trusted-fingerprint',
                     self.details['fingerprint_sha256']]
        if command == 'export':
            args += ['--output', str(self.output)]
        return parser().parse_args(args)

    def test_inspect_prints_only_anonymous_counts(self):
        result = perform(
            self.options(), password_reader=lambda prompt: PASSWORD,
            confirmation_reader=self.confirm)
        self.assertTrue(result['decryption_verified'])
        self.assertEqual(result['normalized_records'], 1)
        for token in (SECRET, FILE_ID, PASSWORD, str(self.vault)):
            self.assertNotIn(token, json.dumps(result))
        self.assertFalse(self.output.exists())

    def test_export_requires_exact_confirmation(self):
        with self.assertRaises(PermissionError):
            perform(
                self.options('export'),
                password_reader=lambda prompt: PASSWORD,
                confirmation_reader=lambda prompt: (
                    'NO' if 'EXPORT-PRIVATE-PLAINTEXT' in prompt
                    else self.confirm(prompt)))
        self.assertFalse(self.output.exists())
        result = perform(
            self.options('export'),
            password_reader=lambda prompt: PASSWORD,
            confirmation_reader=self.confirm)
        self.assertTrue(result['plaintext_file_created'])

    def test_secret_command_line_option_not_echoed(self):
        args = ['inspect', '--vault', str(self.vault),
                '--artifact', str(self.artifact),
                '--trusted-fingerprint', self.details['fingerprint_sha256'],
                '--password', PASSWORD]
        error = io.StringIO()
        with redirect_stderr(error), self.assertRaises(SystemExit):
            parser().parse_args(args)
        self.assertNotIn(PASSWORD, error.getvalue())
        self.assertIn('no secrets', error.getvalue())

    def test_cli_refuses_noninteractive_stdin(self):
        out, error = io.StringIO(), io.StringIO()
        result = main(
            ['inspect', '--vault', str(self.vault),
             '--artifact', str(self.artifact),
             '--trusted-fingerprint', self.details['fingerprint_sha256']],
            stdin=io.StringIO(), stderr=error, stdout=out,
            password_reader=lambda _: self.fail('must not request password'))
        self.assertEqual(result, 2)
        self.assertEqual(out.getvalue(), '')
        self.assertFalse(self.output.exists())

    def test_cli_error_hides_paths_and_passphrase(self):
        output, error = io.StringIO(), _FakeTTY()
        result = main(
            ['inspect', '--vault', str(self.vault),
             '--artifact', str(self.artifact),
             '--trusted-fingerprint', self.details['fingerprint_sha256']],
            stdin=_FakeTTY(), stderr=error, stdout=output,
            confirmation_reader=self.confirm,
            password_reader=lambda prompt: 'incorrect long passphrase')
        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue(), '')
        for sensitive in (PASSWORD, SECRET, FILE_ID, str(self.vault)):
            self.assertNotIn(sensitive, error.getvalue())

    def test_key_init_requires_matching_password_confirmation(self):
        target = self.private_dir / 'new-owner-key.vault'
        options = parser().parse_args(
            ['init-key', '--vault', str(target)])
        answers = iter([PASSWORD, PASSWORD+'different'])
        with self.assertRaises(ValueError):
            perform(
                options, password_reader=lambda prompt: next(answers),
                confirmation_reader=self.confirm)
        self.assertFalse(target.exists())
        responses = iter([PASSWORD, PASSWORD])
        result = perform(
            options, password_reader=lambda prompt: next(responses),
            confirmation_reader=self.confirm)
        self.assertTrue(result['vault_created'])
        self.assertTrue(target.exists())
        self.assertNotIn(PASSWORD, json.dumps(result))


if __name__ == '__main__':
    unittest.main()
