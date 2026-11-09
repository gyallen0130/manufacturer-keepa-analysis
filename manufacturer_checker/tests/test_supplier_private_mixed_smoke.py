"""Synthetic-only regression for the manual private mixed-source smoke gate."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from openpyxl import Workbook
from supplier_docs.private_mixed_smoke import main, run_private_mixed_smoke
from supplier_docs.local_excel_bridge import SCHEMA_VERSION as EXCEL_SCHEMA, MODE as EXCEL_MODE
from supplier_docs.sheets_multi_bridge import SCHEMA_VERSION as SHEETS_SCHEMA, MODE as SHEETS_MODE

FAKE_JAN = "0000000000017"
FAKE_ID = "FAKE_SHEET_001"


class _Reply:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return deepcopy(self.value)


class _FakeSheets:
    def __init__(self):
        self.calls = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **kwargs):
        if "fields" in kwargs:
            self.calls.append("metadata")
            return _Reply({"sheets": [{"properties": {
                "title": "Sheet1", "hidden": False, "sheetType": "GRID",
            }}]})
        self.calls.append("values")
        return _Reply({"values": [
            ["商品名", "JAN", "ASIN"],
            ["架空Sheets商品", FAKE_JAN, "B0TEST0001"],
        ]})


class PrivateMixedSmokeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        book = Workbook()
        page = book.active
        page.title = "Quote"
        page.append(["商品名", "JAN", "ASIN"])
        page.append(["架空Excel商品", FAKE_JAN, "B0TEST0001"])
        book.save(self.root / "approved.xlsx")
        book.close()
        self.original = (self.root / "approved.xlsx").read_bytes()
        self.excel = {
            "schema_version": EXCEL_SCHEMA, "mode": EXCEL_MODE,
            "targets": [{"relative_path": "approved.xlsx",
                         "sheet_name": "Quote", "document_type": "quote_request"}],
        }
        self.sheets = {
            "schema_version": SHEETS_SCHEMA, "mode": SHEETS_MODE,
            "targets": [{"spreadsheet_id": FAKE_ID,
                         "title": "Sheet1", "document_type": "quote_request"}],
        }
        self.search = {"field": "jan", "query": FAKE_JAN}
        self.service = _FakeSheets()
        self.factory_calls = 0
        self.save_inputs()

    def save_inputs(self):
        for filename, data in (("approved_excel.json", self.excel),
                               ("approved_sheets.json", self.sheets),
                               ("approved_search.json", self.search)):
            (self.root / filename).write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )

    def factory(self):
        self.factory_calls += 1
        return self.service

    def test_default_preflight_does_not_attempt_auth_or_sheet_read(self):
        result = run_private_mixed_smoke(
            private_dir=self.root, service_factory=self.factory)
        self.assertEqual(result["status"], "offline_preflight_only")
        self.assertEqual(result["excel_tabs_checked"], 1)
        self.assertEqual(result["sheets_tabs_not_yet_read"], 1)
        self.assertEqual(result["google_api_calls"], 0)
        self.assertEqual(self.factory_calls, 0)
        self.assertEqual(self.service.calls, [])
        self.assertFalse(result["real_google_auth_verified"])
        self.assertEqual((self.root / "approved.xlsx").read_bytes(), self.original)
        self.assertNotIn(FAKE_JAN, json.dumps(result))

    def test_explicit_service_only_returns_safe_public_summaries(self):
        result = run_private_mixed_smoke(
            private_dir=self.root, execute_readonly=True,
            service_factory=self.factory)
        self.assertEqual(result["status"], "readonly_service_probe_completed")
        self.assertEqual(result["public_summary"]["record_count"], 2)
        self.assertEqual(result["public_search_summary"]["hits_returned"], 2)
        self.assertEqual(self.factory_calls, 1)
        self.assertEqual(self.service.calls, ["metadata", "values"])
        self.assertFalse(result["real_google_auth_verified"])
        text = json.dumps(result, ensure_ascii=False)
        for secret in (FAKE_JAN, FAKE_ID, "approved.xlsx", "架空Excel商品",
                       "架空Sheets商品", str(self.root)):
            self.assertNotIn(secret, text)
        self.assertEqual((self.root / "approved.xlsx").read_bytes(), self.original)

    def test_live_requires_explicit_factory(self):
        with self.assertRaises(ValueError):
            run_private_mixed_smoke(
                private_dir=self.root, execute_readonly=True)

    def test_invalid_search_rejected_before_google_client(self):
        self.search = {"field": "jan", "query": "invalid"}
        self.save_inputs()
        with self.assertRaises(ValueError):
            run_private_mixed_smoke(
                private_dir=self.root, execute_readonly=True,
                service_factory=self.factory)
        self.assertEqual(self.factory_calls, 0)

    def test_more_than_five_total_tabs_rejected_before_google(self):
        self.excel["targets"] = [
            dict(self.excel["targets"][0], sheet_name=f"Quote{i}")
            for i in range(4)
        ]
        self.sheets["targets"] = [
            dict(self.sheets["targets"][0], title=f"Sheet{i}")
            for i in range(2)
        ]
        self.save_inputs()
        with self.assertRaises(ValueError):
            run_private_mixed_smoke(
                private_dir=self.root, execute_readonly=True,
                service_factory=self.factory)
        self.assertEqual(self.factory_calls, 0)

    def test_missing_excel_rejected_without_google(self):
        self.excel["targets"][0]["relative_path"] = "missing.xlsx"
        self.save_inputs()
        with self.assertRaises((OSError, ValueError)):
            run_private_mixed_smoke(
                private_dir=self.root, execute_readonly=True,
                service_factory=self.factory)
        self.assertEqual(self.factory_calls, 0)

    def test_reject_symlinked_private_manifest(self):
        manifest = self.root / "approved_search.json"
        alternate = self.root / "outside.json"
        alternate.write_text(json.dumps(self.search), encoding="utf-8")
        manifest.unlink()
        manifest.symlink_to(alternate)
        with self.assertRaises(ValueError):
            run_private_mixed_smoke(private_dir=self.root)

    def test_cli_error_hides_private_filename_and_identifier(self):
        self.search = {"field": "jan", "query": "SECRET_FAKE_QUERY"}
        self.save_inputs()
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(["--private-dir", str(self.root)])
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertNotIn("SECRET_FAKE_QUERY", stderr.getvalue())
        self.assertNotIn(str(self.root), stderr.getvalue())

    def test_cli_success_is_bounded_offline_json(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(["--private-dir", str(self.root)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["status"], "offline_preflight_only")
        self.assertEqual(result["google_api_calls"], 0)


if __name__ == "__main__":
    unittest.main()
