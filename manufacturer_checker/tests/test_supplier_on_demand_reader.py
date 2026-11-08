"""No live Google API, real supplier data, credentials or paid cloud resources."""
from copy import deepcopy
import io
import json
import unittest
from unittest.mock import patch, Mock

from supplier_docs.on_demand_reader import (
    SCHEMA, validate_manual_sheet_manifest,
    inspect_manual_approved_sheets,
)
from supplier_docs.manual_sheet_probe import (
    validate_private_manual_runner, main,
)
from supplier_docs.auth import SHEETS_READONLY_SCOPE, build_readonly_sheets_service_from_wif_adc

FILE1 = 'fake_private_sheet_1234'
FILE2 = 'fake_private_sheet_5678'
SENSITIVE_VENDOR = 'FAKE-PRIVATE-SELLER-XY'
SENSITIVE_NAME = 'FAKE-PRIVATE-PRODUCT-ZZ'
SENSITIVE_JAN = '0012345678901'
SENSITIVE_ASIN = 'B0ABCDEF12'
SENSITIVE_PRICE = '1234'
TAB = "見積'2026"


def approved(*, files=None):
    if files is None:
        files = [{'spreadsheet_id': FILE1, 'tabs': [
            {'title': TAB, 'document_type': 'quote_response'}]}]
    return {'schema_version': SCHEMA, 'mode': 'manual_readonly', 'targets': files}


class _Result:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeSheets:
    def __init__(self, *, hidden=None, fail_values=False):
        self.calls = []
        self.hidden = set(hidden or [])
        self.fail_values = fail_values

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **kwargs):
        if 'fields' in kwargs:
            self.calls.append(('metadata', kwargs['spreadsheetId']))
            return _Result({'sheets': [{'properties': {
                'title': TAB, 'sheetType': 'GRID',
                'hidden': kwargs['spreadsheetId'] in self.hidden}}]})
        self.calls.append(('values', kwargs['spreadsheetId'], kwargs['range'],
                           kwargs['valueRenderOption']))
        if self.fail_values:
            raise RuntimeError('PRIVATE ID ' + FILE1 + ' source failed')
        return _Result({'values': [
            ['メーカー', '商品名', 'JAN', 'ASIN', '卸値'],
            [SENSITIVE_VENDOR, SENSITIVE_NAME, SENSITIVE_JAN,
             SENSITIVE_ASIN, SENSITIVE_PRICE],
        ]})


class ManualOnDemandReaderTests(unittest.TestCase):

    def test_direct_inspection_returns_private_products_separately(self):
        svc = FakeSheets()
        r = inspect_manual_approved_sheets(
            svc, manifest=approved(), include_sensitive_records=True)
        self.assertEqual(r['public_summary']['normalized_records'], 1)
        self.assertTrue(r['public_summary']['review_required'])
        self.assertEqual(r['public_summary']['source_write_operations'], 0)
        record = r['private_inspections'][0]['tabs'][0]['records'][0]
        self.assertEqual(record['manufacturer_name_raw'], SENSITIVE_VENDOR)
        self.assertEqual(record['product_name_raw'], SENSITIVE_NAME)
        self.assertEqual(record['jan_string'], SENSITIVE_JAN)
        self.assertEqual(record['asin_candidate'], SENSITIVE_ASIN)
        self.assertEqual(record['cost_amount'], SENSITIVE_PRICE)
        self.assertIn('values', [x[0] for x in svc.calls])
        self.assertEqual(svc.calls[1][2], "'見積''2026'!A1:L100")
        self.assertEqual(svc.calls[1][3], 'FORMULA')
        for secret in (FILE1, TAB, SENSITIVE_VENDOR, SENSITIVE_NAME,
                       SENSITIVE_JAN, SENSITIVE_ASIN, SENSITIVE_PRICE):
            self.assertNotIn(secret, json.dumps(r['public_summary'],
                                                 ensure_ascii=False))

    def test_default_private_records_do_not_include_raw_prices(self):
        r = inspect_manual_approved_sheets(
            FakeSheets(), manifest=approved())
        record = r['private_inspections'][0]['tabs'][0]['records'][0]
        self.assertNotIn('cost_amount', record)
        self.assertEqual(r['public_summary']['normalized_records'], 1)

    def test_two_files_metadata_preflight_before_any_cells(self):
        svc = FakeSheets()
        config = approved(files=[
            {'spreadsheet_id': FILE1, 'tabs': [
                {'title': TAB, 'document_type': 'quote_response'}]},
            {'spreadsheet_id': FILE2, 'tabs': [
                {'title': TAB, 'document_type': 'quote_response'}]},
        ])
        report = inspect_manual_approved_sheets(svc, manifest=config)
        self.assertEqual(report['public_summary']['normalized_records'], 2)
        self.assertEqual([x[0] for x in svc.calls],
                         ['metadata', 'metadata', 'values', 'values'])

    def test_hidden_selected_tab_fails_before_any_values_access(self):
        svc = FakeSheets(hidden={FILE2})
        config = approved(files=[
            {'spreadsheet_id': FILE1, 'tabs': [
                {'title': TAB, 'document_type': 'quote_response'}]},
            {'spreadsheet_id': FILE2, 'tabs': [
                {'title': TAB, 'document_type': 'quote_response'}]},
        ])
        with self.assertRaises(ValueError):
            inspect_manual_approved_sheets(svc, manifest=config)
        self.assertEqual([x[0] for x in svc.calls], ['metadata', 'metadata'])

    def test_invalid_manifest_fails_before_any_google_calls(self):
        valid = approved()
        cases = []
        for k, value in [('schema_version', 'old'),
                         ('mode', 'auto_write'),
                         ('targets', []),
                         ('targets', [valid['targets'][0]] * 4)]:
            bad = deepcopy(valid)
            bad[k] = value
            cases.append(bad)
        for changes in [
            {'spreadsheet_id': 'INVALID!ID'},
            {'spreadsheet_id': FILE1, 'extra': 'danger'},
            {'tabs': []},
            {'tabs': [{'title': TAB, 'document_type': []}]},
            {'tabs': [{'title': TAB, 'document_type': 'unknown'}]},
            {'tabs': [{'title': 'bad!tab', 'document_type': 'quote_response'}]},
            {'tabs': [{'title': TAB, 'document_type': 'quote_response'}] * 2},
        ]:
            bad = deepcopy(valid)
            bad['targets'][0].update(changes)
            cases.append(bad)
        bad = approved(files=[valid['targets'][0], valid['targets'][0]])
        cases.append(bad)
        bad = deepcopy(valid)
        bad['unexpected'] = True
        cases.append(bad)
        for case in cases:
            svc = FakeSheets()
            with self.subTest(case=case), self.assertRaises(ValueError):
                inspect_manual_approved_sheets(svc, manifest=case)
            self.assertEqual(svc.calls, [])

    def test_bounded_total_cells_for_six_tabs(self):
        config = approved(files=[
            {'spreadsheet_id': FILE1, 'tabs': [
                {'title': f'Tab{i}', 'document_type': 'catalog'}
                for i in range(4)]},
            {'spreadsheet_id': FILE2, 'tabs': [
                {'title': f'Other{i}', 'document_type': 'catalog'}
                for i in range(3)]},
        ])
        with self.assertRaises(ValueError):
            validate_manual_sheet_manifest(config)

    def test_unexpected_remote_failure_carries_no_log_in_manual_runner(self):
        env = valid_env()
        out, err = io.StringIO(), io.StringIO()
        rc = main(environ=env, service_factory=lambda: FakeSheets(fail_values=True),
                  stdout=out, stderr=err)
        self.assertEqual(rc, 1)
        self.assertEqual(out.getvalue(), '')
        self.assertNotIn(FILE1, err.getvalue())
        self.assertNotIn(SENSITIVE_VENDOR, err.getvalue())

    def test_public_runner_denied_before_auth_or_api(self):
        for k,v in [
            ('GITHUB_ACTIONS', 'false'),
            ('GITHUB_EVENT_NAME', 'pull_request'),
            ('GITHUB_EVENT_NAME', 'schedule'),
            ('GITHUB_REF', 'refs/heads/not-reviewed'),
            ('SUPPLIER_REPO_PRIVATE', 'false'),
            ('GITHUB_WORKFLOW_REF', 'fake-owner/private/'
             '.github/workflows/other.yml@refs/heads/main'),
            ('GITHUB_REPOSITORY_ID', 'fake-name'),
            ('GOOGLE_APPLICATION_CREDENTIALS', ''),
        ]:
            env = valid_env()
            env[k] = v
            called = []
            out, err = io.StringIO(), io.StringIO()
            rc = main(environ=env,
                      service_factory=lambda: called.append('called'),
                      stdout=out, stderr=err)
            with self.subTest(key=k):
                self.assertEqual(rc, 1)
                self.assertEqual(called, [])
                self.assertEqual(out.getvalue(), '')

    def test_runner_success_prints_summary_only_not_private_records(self):
        output, errors = io.StringIO(), io.StringIO()
        result = main(environ=valid_env(), service_factory=FakeSheets,
                      stdout=output, stderr=errors)
        self.assertEqual(result, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report['normalized_records'], 1)
        self.assertEqual(report['cloud_storage_writes'], 0)
        self.assertEqual(report['automatic_purchases'], 0)
        self.assertEqual(errors.getvalue(), '')
        for sensitive in (FILE1, TAB, SENSITIVE_VENDOR,
                          SENSITIVE_NAME, SENSITIVE_JAN, SENSITIVE_ASIN,
                          SENSITIVE_PRICE):
            self.assertNotIn(sensitive, output.getvalue())

    def test_malformed_json_denied_and_not_printed(self):
        env = valid_env()
        env['SUPPLIER_READ_MANIFEST_JSON'] = '{"secret": "VERY_SENSITIVE'
        err = io.StringIO()
        rc = main(environ=env, service_factory=lambda: None,
                  stdout=io.StringIO(), stderr=err)
        self.assertEqual(rc, 1)
        self.assertNotIn('VERY_SENSITIVE', err.getvalue())

    @patch('googleapiclient.discovery.build')
    @patch('google.auth.default')
    def test_wif_client_requests_sheets_readonly_only(self, adc, build):
        credentials = object()
        adc.return_value = (credentials, 'fake-project')
        build.return_value = object()
        client = build_readonly_sheets_service_from_wif_adc()
        self.assertIs(client, build.return_value)
        adc.assert_called_once_with(scopes=[SHEETS_READONLY_SCOPE])
        build.assert_called_once_with('sheets', 'v4',
                                      credentials=credentials,
                                      cache_discovery=False)


def valid_env():
    repo = 'fake-owner/private'
    return {
        'GITHUB_ACTIONS': 'true',
        'SUPPLIER_REPO_PRIVATE': 'true',
        'GITHUB_EVENT_NAME': 'workflow_dispatch',
        'GITHUB_REF': 'refs/heads/main',
        'GITHUB_REPOSITORY': repo,
        'GITHUB_REPOSITORY_ID': '1234567890',
        'GITHUB_REPOSITORY_OWNER_ID': '9876543210',
        'GITHUB_WORKFLOW_REF': (
            repo + '/.github/workflows/supplier-readonly.yml@refs/heads/main'),
        'GOOGLE_APPLICATION_CREDENTIALS': '/fake-gh-wif-credentials.json',
        'SUPPLIER_READ_MANIFEST_JSON': json.dumps(approved()),
    }


if __name__ == '__main__':
    unittest.main()
