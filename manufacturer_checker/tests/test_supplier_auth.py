"""Offline checks for keyless, least-privileged Google Sheets smoke access.

No actual Google credentials, supplier IDs, requests, or network calls.
"""
import contextlib
import io
import unittest
from unittest.mock import Mock, patch

from supplier_docs.auth import SHEETS_READONLY_SCOPE, build_readonly_sheets_service
from supplier_docs.cli import main


class SupplierAuthenticationTests(unittest.TestCase):

    def test_malformed_or_missing_target_rejected_before_adc(self):
        for value in (None, '', 'owner@gmail.com', 'not-an-email',
                      'prod@!.iam.gserviceaccount.com',
                      'badtarget@somewhere.example.com', 'mixed.Case@x-xxxx.iam.gserviceaccount.com'):
            with self.assertRaises(ValueError, msg=repr(value)):
                build_readonly_sheets_service(value)

    @patch('googleapiclient.discovery.build')
    @patch('google.auth.impersonated_credentials.Credentials')
    @patch('google.auth.default')
    def test_only_impersonated_read_scope_is_passed_to_sheets(self, adc, impersonate, build):
        source, target, client = object(), object(), object()
        adc.return_value = (source, 'fake-test-project')
        impersonate.return_value = target
        build.return_value = client

        result = build_readonly_sheets_service('supplier-reader@fake-project-123.iam.gserviceaccount.com')
        self.assertIs(result, client)
        adc.assert_called_once_with()
        impersonate.assert_called_once_with(
            source_credentials=source,
            target_principal='supplier-reader@fake-project-123.iam.gserviceaccount.com',
            target_scopes=[SHEETS_READONLY_SCOPE],
            lifetime=900)
        build.assert_called_once_with(
            'sheets', 'v4', credentials=target, cache_discovery=False)

    @patch('googleapiclient.discovery.build')
    @patch('google.auth.impersonated_credentials.Credentials')
    @patch('google.auth.default')
    def test_supplied_adc_source_is_not_reloaded(self, adc, impersonate, build):
        source = object()
        build_readonly_sheets_service(
            'supplier-reader@fake-project-123.iam.gserviceaccount.com',
            source_credentials=source)
        adc.assert_not_called()
        self.assertIs(impersonate.call_args.kwargs['source_credentials'], source)

    def test_remote_cli_rejects_implicit_adc_or_detailed_output(self):
        base = ['--sheets-id', 'fake-sheet-id', '--sheet-range', "'Example'!A1:B10",
                '--document-type', 'quote_request']
        cases = [
            base,
            base + ['--summary-only'],
            base + ['--impersonate-service-account', 'supplier-reader@fake-project-123.iam.gserviceaccount.com'],
        ]
        for args in cases:
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    main(args)
            self.assertEqual(cm.exception.code, 2)

    @patch('supplier_docs.auth.build_readonly_sheets_service')
    @patch('supplier_docs.cli.sheets_values')
    def test_remote_summary_smoke_redacts_identifiers(self, sheets, build):
        sheets.return_value = [
            ['メーカー', '商品名', 'JAN', 'ASIN'],
            ['機密仕入先', '極秘商品', '0012345678901', 'B012345678']
        ]
        service = Mock()
        build.return_value = service
        base = ['--sheets-id', 'fake-private-sheet-id',
                '--sheet-range', "'Sheet1'!A1:D2",
                '--document-type', 'quote_request',
                '--impersonate-service-account', 'supplier-reader@fake-project-123.iam.gserviceaccount.com',
                '--summary-only']
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(base), 0)
        printed = output.getvalue()
        for val in ('機密仕入先', '極秘商品', '0012345678901', 'B012345678', 'fake-private-sheet-id'):
            self.assertNotIn(val, printed)
        self.assertIn('"record_count": 1', printed)
        build.assert_called_once_with('supplier-reader@fake-project-123.iam.gserviceaccount.com')
        sheets.assert_called_once_with(service, spreadsheet_id='fake-private-sheet-id',
                                      sheet_range="'Sheet1'!A1:D2")


if __name__ == '__main__':
    unittest.main()
