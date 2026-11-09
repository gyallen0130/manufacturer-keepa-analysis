"""Synthetic-only end-to-end one-call supplier lookup workflow tests."""
from copy import deepcopy
import json
import unittest

from supplier_docs.supplier_lookup_session import run_supplier_lookup_once

ID_A = "SYNTHETIC_FILE_A_0000001"
ID_B = "SYNTHETIC_FILE_B_0000002"
JAN = "0000000000017"
ASIN = "B0TEST0001"
CONTEXT = {
    "source_access_checked": True,
    "private_recipient_checked": True,
    "private_display_requested": True,
    "no_public_logging": True,
}


def metadata(label="架空卸問屋A", file_id=ID_A, tab="見積もり", gid=37,
             rows=79):
    return {
        "supplier_label": label,
        "spreadsheet_id": file_id,
        "sheet_name": tab,
        "sheet_gid": gid,
        "grid_rows": rows,
        "grid_columns": 30,
        "header_row": 1,
        "document_type": "quote_request",
        "visible": True,
        "source_access_checked": True,
    }


class FakeAuthenticatedConnector:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.mutate = None
    def __call__(self, *, spreadsheet_id, sheet_name, requested_range,
                 value_render_option):
        self.calls.append((spreadsheet_id, sheet_name, requested_range,
                           value_render_option))
        if self.failure:
            raise ValueError("PRIVATE file id or secret token: " + self.failure)
        assert value_render_option == "FORMULA"
        start, end = requested_range.replace("A", "").replace("O", "").split(":")
        lo, hi = int(start), int(end)
        rows = ([["商品名", "JAN", "ASIN", "仕入価格"]] if lo == 1 and hi == 1
                else [
                    [f"架空商品{row}", JAN if row == 41 else "4901234567894",
                     ASIN if row == 41 else "B0TEST0002",
                     "=SECRET" if row == 41 else 733]
                    for row in range(lo, hi + 1)
                ])
        reply = {
            "spreadsheet_id": spreadsheet_id,
            "sheet_name": sheet_name,
            "requested_range": requested_range,
            "value_render_option": value_render_option,
            "rows": rows,
        }
        if self.mutate is not None:
            self.mutate(reply)
        return reply


class SupplierLookupSessionTests(unittest.TestCase):
    def execute(self, *, reader=None, catalog=None, private=False, query=None,
                search=None, ctx=None, **kwargs):
        return run_supplier_lookup_once(
            supplier_query=query if query is not None else "架空卸問屋A",
            search=search if search is not None else {"field": "jan", "query": JAN},
            approved_tab_metadata=catalog if catalog is not None
                else [metadata(), metadata("架空卸問屋B", ID_B, "取扱メーカー", 49)],
            fetch_formula_range=reader if reader is not None
                else FakeAuthenticatedConnector(),
            include_private_hits=private,
            reviewer_context=ctx if ctx is not None else (
                CONTEXT if private else None),
            **kwargs,
        )

    def test_one_call_searches_only_selected_supplier_and_next_page(self):
        reader = FakeAuthenticatedConnector()
        result = self.execute(reader=reader)
        self.assertEqual(len(reader.calls), 3)
        self.assertEqual([call[2] for call in reader.calls],
                         ["A1:O1", "A2:O40", "A41:O79"])
        self.assertTrue(all(call[0] == ID_A for call in reader.calls))
        self.assertTrue(all(call[3] == "FORMULA" for call in reader.calls))
        self.assertEqual(result["public_search_summary"]["hits_returned"], 1)
        self.assertEqual(result["public_summary"]["record_count"], 78)
        self.assertEqual(result["coverage"]["planned_page_reads"], 2)
        self.assertFalse(result["private_details_returned"])
        self.assertTrue(result["external_authentication_required"])

    def test_private_hit_uses_exact_source_gid_and_original_row(self):
        result = self.execute(private=True)
        self.assertTrue(result["private_details_returned"])
        review = result["private_review"]
        self.assertEqual(review["matched_hits_total"], 1)
        hit = review["private_hits"][0]
        self.assertEqual(hit["original_physical_row"], 41)
        self.assertEqual(hit["product_name"], "架空商品41")
        self.assertEqual(hit["jan_candidate"], JAN)
        url = "https://docs.google.com/spreadsheets/d/" + ID_A + "/edit"
        self.assertEqual(hit["original_row_url"],
                         url + "#gid=37&range=A41:O41")
        self.assertTrue(hit["candidate_only"])
        self.assertFalse(hit["purchase_allowed"])
        self.assertFalse(result["python_google_auth_verified"])

    def test_public_response_contains_no_identifiers_prices_names_or_formula(self):
        output = self.execute()
        raw = json.dumps(output, ensure_ascii=False)
        for token in (ID_A, ID_B, "架空卸問屋A", "架空商品41", JAN,
                      ASIN, "SECRET", "733", "見積もり", "A41:O79"):
            self.assertNotIn(token, raw)

    def test_unapproved_supplier_never_causes_connector_call(self):
        reader = FakeAuthenticatedConnector()
        with self.assertRaises(ValueError):
            self.execute(reader=reader, query="未承認卸問屋")
        self.assertEqual(reader.calls, [])

    def test_ambiguous_supplier_never_causes_connector_call(self):
        reader = FakeAuthenticatedConnector()
        with self.assertRaises(ValueError):
            self.execute(reader=reader, query="架空卸問屋")
        self.assertEqual(reader.calls, [])

    def test_no_private_opt_in_fails_before_connector_read(self):
        for ctx in ({}, {**CONTEXT, "no_public_logging": False}):
            reader = FakeAuthenticatedConnector()
            with self.subTest(ctx=ctx), self.assertRaisesRegex(
                    ValueError, "private review"):
                self.execute(private=True, ctx=ctx, reader=reader)
            self.assertEqual(reader.calls, [])

    def test_private_context_without_opt_in_rejected_before_read(self):
        reader = FakeAuthenticatedConnector()
        with self.assertRaises(ValueError):
            self.execute(reader=reader, ctx=CONTEXT)
        self.assertEqual(reader.calls, [])

    def test_callback_error_redacted_without_leaking_id_or_secret(self):
        reader = FakeAuthenticatedConnector()
        reader.failure = ID_A + " SENSITIVE_API_TOKEN_123"
        with self.assertRaises(RuntimeError) as caught:
            self.execute(reader=reader)
        self.assertEqual(str(caught.exception),
                         "authorized connector range read failed")
        self.assertNotIn(ID_A, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_render_mode_mismatch_is_not_silently_parsed(self):
        reader = FakeAuthenticatedConnector()
        reader.mutate = lambda x: x.update(value_render_option="FORMATTED_VALUE")
        with self.assertRaisesRegex(ValueError, "FORMULA"):
            self.execute(reader=reader)

    def test_swapped_file_response_rejected(self):
        reader = FakeAuthenticatedConnector()
        reader.mutate = lambda x: x.update(spreadsheet_id=ID_B)
        with self.assertRaisesRegex(ValueError, "range binding"):
            self.execute(reader=reader)

    def test_swapped_range_response_rejected(self):
        reader = FakeAuthenticatedConnector()
        reader.mutate = lambda x: x.update(requested_range="A80:O118")
        with self.assertRaisesRegex(ValueError, "range binding"):
            self.execute(reader=reader)

    def test_unknown_response_key_rejected(self):
        reader = FakeAuthenticatedConnector()
        reader.mutate = lambda x: x.update(access_token="SECRET")
        with self.assertRaisesRegex(ValueError, "envelope"):
            self.execute(reader=reader)

    def test_invalid_search_prevents_connector_access(self):
        reader = FakeAuthenticatedConnector()
        with self.assertRaises(ValueError):
            self.execute(reader=reader, search={"field": "jan", "query": "x"})
        self.assertEqual(reader.calls, [])

    def test_zero_hits_never_means_all_suppliers_searched(self):
        result = self.execute(search={"field": "jan", "query": "0000000000099"})
        self.assertEqual(result["public_search_summary"]["hits_returned"], 0)
        self.assertFalse(
            result["public_summary"]["all_supplier_folders_searched"])
        self.assertFalse(result["coverage"]["all_product_rows_verified"])

    def test_one_tab_empty_page_is_not_network_failure(self):
        reader = FakeAuthenticatedConnector()
        def make_last_empty(resp):
            if resp["requested_range"] == "A41:O79":
                resp["rows"] = []
        reader.mutate = make_last_empty
        result = self.execute(reader=reader)
        self.assertEqual(result["public_search_summary"]["hits_returned"], 0)
        self.assertEqual(
            result["public_summary"]["trailing_rows_unpopulated_in_connector_response"],39)

    def test_two_tabs_same_workbook_never_guess_wrong_gid(self):
        approved = [
            metadata(file_id=ID_A, tab="見積もり", gid=11),
            metadata(file_id=ID_A, tab="一覧", gid=22),
        ]
        result = self.execute(private=True, catalog=approved)
        self.assertEqual(result["private_review"]["hits_displayed"], 2)
        hits = result["private_review"]["private_hits"]
        self.assertEqual({hit["original_sheet_tab"] for hit in hits},
                         {"見積もり", "一覧"})
        self.assertTrue(all(hit["original_row_url"] is None for hit in hits))

    def test_source_metadata_and_searched_rows_never_modified(self):
        catalog = [metadata()]
        before = deepcopy(catalog)
        result = self.execute(catalog=catalog, private=True)
        self.assertEqual(catalog, before)
        self.assertEqual(result["source_writes"], 0)


if __name__ == "__main__":
    unittest.main()
