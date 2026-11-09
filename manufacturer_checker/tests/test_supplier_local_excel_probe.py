"""Synthetic-only CLI checks; never load real supplier files in public CI."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from openpyxl import Workbook

from supplier_docs.local_excel_probe import main
from supplier_docs.local_excel_bridge import SCHEMA_VERSION, MODE


JAN = '0000000000017'


class PrivateExcelProbeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        w = Workbook()
        sheet = w.active
        sheet.title = 'Quote'
        sheet.append(['商品名', 'JAN', 'ASIN'])
        sheet.append(['FAKE_PRIVATE_PRODUCT', JAN, 'B0TEST0001'])
        w.save(self.root / 'fake_quote.xlsx')
        w.close()
        self.manifest = self.root / 'manifest.json'
        self.manifest.write_text(json.dumps({
            'schema_version': SCHEMA_VERSION, 'mode': MODE,
            'targets': [{'relative_path': 'fake_quote.xlsx',
                         'sheet_name': 'Quote', 'document_type': 'quote_response'}],
        }), encoding='utf-8')
        self.search = self.root / 'lookup.json'
        self.search.write_text(json.dumps({'field': 'jan', 'query': JAN}),
                               encoding='utf-8')

    def run_cli(self, *extra):
        stdout, stderr = StringIO(), StringIO()
        argv = ['--root', str(self.root), '--manifest', str(self.manifest), *extra]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(argv)
        return status, stdout.getvalue(), stderr.getvalue()

    def test_only_aggregate_json_and_no_raw_product_or_file(self):
        status, output, errors = self.run_cli()
        self.assertEqual(status, 0, errors)
        value = json.loads(output)
        self.assertEqual(value['summary']['source_count'], 1)
        self.assertEqual(value['summary']['record_count'], 1)
        self.assertFalse(value['summary']['profit_calculation_allowed'])
        for token in ('FAKE_PRIVATE_PRODUCT', JAN, 'B0TEST0001',
                      'fake_quote.xlsx', str(self.root)):
            self.assertNotIn(token, output)

    def test_lookup_returns_aggregate_and_never_the_query(self):
        status, output, errors = self.run_cli(
            '--search-manifest', str(self.search))
        self.assertEqual(status, 0, errors)
        value = json.loads(output)
        self.assertEqual(value['search_summary']['hits_returned'], 1)
        self.assertNotIn(JAN, output)
        self.assertFalse(value['search_summary']['all_supplier_folders_searched'])

    def test_original_excel_bytes_not_modified(self):
        source = self.root / 'fake_quote.xlsx'
        digest = hashlib.sha256(source.read_bytes()).digest()
        status, _, _ = self.run_cli()
        self.assertEqual(status, 0)
        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), digest)

    def test_invalid_json_input_is_rejected_without_path_or_data(self):
        self.manifest.write_text('SECRET_PRIVATE_ITEM:= malformed {',
                                 encoding='utf-8')
        status, output, errors = self.run_cli()
        self.assertEqual(status, 2)
        self.assertEqual(output, '')
        self.assertNotIn('SECRET_PRIVATE_ITEM', errors)
        self.assertNotIn(str(self.manifest), errors)

    def test_bad_search_source_is_not_echoed(self):
        self.search.write_text(json.dumps(
            {'field': 'jan', 'query': 'SECRET_JAN_INPUT'}),
            encoding='utf-8')
        status, output, errors = self.run_cli(
            '--search-manifest', str(self.search))
        self.assertEqual(status, 2)
        self.assertNotIn('SECRET_JAN_INPUT', output + errors)

    def test_reject_large_or_unapproved_manifest(self):
        self.manifest.write_text('x' * 32769, encoding='utf-8')
        status, _, errors = self.run_cli()
        self.assertEqual(status, 2)
        self.assertIn('rejected', errors)


if __name__ == '__main__':
    unittest.main()
