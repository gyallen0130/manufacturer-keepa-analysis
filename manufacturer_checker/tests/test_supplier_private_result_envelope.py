"""No Google access, GitHub secrets, real prices or persistent keys."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from supplier_docs.private_result_envelope import (
    VERSION, recipient_public_key_b64, seal_private_inspections,
    open_private_inspections,
)
from supplier_docs.private_result_file import (
    FILENAME, stage_owner_report, write_encrypted_owner_result,
)

VENDOR = 'FAKE_SUPPLIER_CONFIDENTIAL'
PRODUCT = 'FAKE_PRODUCT_CONFIDENTIAL'
PRICE = 'FAKE_PRICE_1234'
SHEET = 'fake_sheet_secret_xxxx'
FAKE_REPORT = {
    'public_summary': {
        'approved_files': 1,
        'normalized_records': 1,
        'source_write_operations': 0,
        'automatic_purchases': 0,
    },
    'private_inspections': [
        {'spreadsheet_id': SHEET, 'tabs': [
            {'title': '価格改定', 'status': 'parsed', 'records': [
                {'manufacturer_name_raw': VENDOR,
                 'product_name_raw': PRODUCT,
                 'cost_amount': PRICE}]}]},
    ],
}


def fixture():
    private = X25519PrivateKey.generate()
    public_b64 = recipient_public_key_b64(private)
    digest = hashlib.sha256(base64.b64decode(public_b64)).hexdigest()
    return private, public_b64, digest


class RecipientEncryptedResultTests(unittest.TestCase):
    def setUp(self):
        self.private, self.public, self.digest = fixture()

    def seal(self, **kw):
        arguments = {
            'recipient_public_key_b64': self.public,
            'trusted_fingerprint_sha256': self.digest,
        }
        arguments.update(kw)
        return seal_private_inspections(FAKE_REPORT, **arguments)

    def open(self, envelope, **kw):
        args = {'recipient_private_key': self.private,
                'trusted_fingerprint_sha256': self.digest}
        args.update(kw)
        return open_private_inspections(envelope, **args)

    def test_owner_only_can_decrypt_complete_private_inspections(self):
        envelope = self.seal()
        self.assertEqual(envelope['schema_version'], VERSION)
        encoded = json.dumps(envelope, sort_keys=True)
        for token in [VENDOR, PRODUCT, PRICE, SHEET]:
            self.assertNotIn(token, encoded)
        restored = self.open(envelope)
        self.assertEqual(restored, FAKE_REPORT)

    def test_envelope_uses_unique_ephemeral_key_nonce_and_ciphertext(self):
        a = self.seal()
        b = self.seal()
        self.assertNotEqual(a['nonce_b64'], b['nonce_b64'])
        self.assertNotEqual(a['ephemeral_public_key_b64'],
                            b['ephemeral_public_key_b64'])
        self.assertNotEqual(a['ciphertext_b64'], b['ciphertext_b64'])
        self.assertEqual(self.open(a), self.open(b))

    def test_different_private_key_cannot_decrypt(self):
        other = X25519PrivateKey.generate()
        with self.assertRaises(ValueError):
            self.open(self.seal(), recipient_private_key=other)

    def test_public_key_replacement_and_pin_mismatch_rejected(self):
        _, alien_public, _ = fixture()
        with self.assertRaises(ValueError):
            self.seal(recipient_public_key_b64=alien_public)
        with self.assertRaises(ValueError):
            self.seal(trusted_fingerprint_sha256='0' * 64)
        with self.assertRaises(ValueError):
            self.seal(trusted_fingerprint_sha256='not-hex')

    def test_all_authenticated_header_fields_are_tamper_evident(self):
        envelope = self.seal()
        other = self.seal()
        for field, replacement in {
            'schema_version': 'other_version',
            'recipient_fingerprint_sha256': 'f' * 64,
            'salt_b64': other['salt_b64'],
            'nonce_b64': other['nonce_b64'],
            'ephemeral_public_key_b64': other['ephemeral_public_key_b64'],
            'ciphertext_b64': other['ciphertext_b64'],
        }.items():
            tampered = {**envelope, field: replacement}
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.open(tampered)

    def test_extra_fields_or_non_ciphertext_envelope_rejected(self):
        envelope = self.seal()
        with self.assertRaises(ValueError):
            self.open({**envelope, 'raw_supplier': VENDOR})
        with self.assertRaises(ValueError):
            self.open({'plaintext': FAKE_REPORT})

    def test_bad_base64_and_short_fields_rejected(self):
        for key in ('', '!', 'AAAA'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.seal(recipient_public_key_b64=key)
        envelope = self.seal()
        for key in ('salt_b64', 'nonce_b64', 'ephemeral_public_key_b64',
                    'ciphertext_b64'):
            bad = {**envelope, key: 'AA=='}
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.open(bad)

    def test_malformed_plain_payload_rejected(self):
        for report in (
            {'public_summary': {}, 'private_inspections': [], 'other': 1},
            {'public_summary': 'text', 'private_inspections': []},
            {'public_summary': {}, 'private_inspections': 'wrong'},
        ):
            with self.subTest(report=report), self.assertRaises(ValueError):
                seal_private_inspections(
                    report, recipient_public_key_b64=self.public,
                    trusted_fingerprint_sha256=self.digest)

    def test_oversized_private_records_rejected_before_encrypting(self):
        large = copy.deepcopy(FAKE_REPORT)
        large['private_inspections'][0]['tabs'][0]['records'][0]['description'] = 'x' * 1_550_000
        with self.assertRaises(ValueError):
            seal_private_inspections(
                large, recipient_public_key_b64=self.public,
                trusted_fingerprint_sha256=self.digest)


class OwnerEncryptedArtifactFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.path = Path(self.root, FILENAME)
        self.private, self.public, self.digest = fixture()

    def stage(self):
        return stage_owner_report(
            FAKE_REPORT, runner_temp=self.root,
            recipient_public_key_b64=self.public,
            trusted_fingerprint_sha256=self.digest)

    def test_staging_creates_ciphertext_only_in_fixed_filename(self):
        result = self.stage()
        self.assertTrue(result['encrypted_result_file_created'])
        self.assertFalse(result['plaintext_file_created'])
        raw = self.path.read_bytes()
        self.assertTrue(len(raw) > 100)
        for token in [VENDOR, PRODUCT, PRICE, SHEET]:
            self.assertNotIn(token.encode(), raw)
        envelope = json.loads(raw)
        restored = open_private_inspections(
            envelope, recipient_private_key=self.private,
            trusted_fingerprint_sha256=self.digest)
        self.assertEqual(restored, FAKE_REPORT)
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_second_attempt_does_not_overwrite_ciphertext(self):
        self.stage()
        original = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            self.stage()
        self.assertEqual(self.path.read_bytes(), original)

    def test_invalid_recipient_never_writes_file(self):
        with self.assertRaises(ValueError):
            stage_owner_report(
                FAKE_REPORT, runner_temp=self.root,
                recipient_public_key_b64=self.public,
                trusted_fingerprint_sha256='0' * 64)
        self.assertFalse(self.path.exists())

    def test_invalid_or_nonexistent_temp_path_rejected(self):
        _, pub, digest = fixture()
        envelope = seal_private_inspections(
            FAKE_REPORT, recipient_public_key_b64=pub,
            trusted_fingerprint_sha256=digest)
        for invalid in ('relative-path', str(Path(self.root, 'missing'))):
            with self.subTest(path=invalid), self.assertRaises((ValueError, FileNotFoundError)):
                write_encrypted_owner_result(envelope, runner_temp=invalid)
        self.assertFalse(self.path.exists())

    def test_plaintext_envelope_cannot_be_staged(self):
        with self.assertRaises(ValueError):
            write_encrypted_owner_result({'raw': FAKE_REPORT},
                                         runner_temp=self.root)
        self.assertFalse(self.path.exists())

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink case')
    def test_symlink_runner_temp_is_rejected(self):
        alias = Path(self.root).parent / (Path(self.root).name + '-alias')
        alias.symlink_to(self.root, target_is_directory=True)
        self.addCleanup(alias.unlink)
        envelope = seal_private_inspections(
            FAKE_REPORT, recipient_public_key_b64=self.public,
            trusted_fingerprint_sha256=self.digest)
        with self.assertRaises(PermissionError):
            write_encrypted_owner_result(envelope, runner_temp=str(alias))
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
