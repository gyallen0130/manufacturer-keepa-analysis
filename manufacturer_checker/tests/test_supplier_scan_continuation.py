"""Offline fictional tests for read-only >200-row supplier scan continuation."""
from copy import deepcopy
import json
import unittest

from supplier_docs.supplier_scan_continuation import (
    scan_next_selected_supplier_sheet, public_scan_progress,
)
from supplier_docs.supplier_drive_version import DRIVE_VERSION_KIND

FID = "SYNTHETIC_LONG_SUPPLIER_00001"
JAN = "0000000000017"
ASIN = "B0TEST0001"
CONTEXT = {
    "source_access_checked": True,
    "private_recipient_checked": True,
    "private_display_requested": True,
    "no_public_logging": True,
}


def approved(*, count=500, header=1, tab="見積もり"):
    return [{
        "supplier_label": "架空卸A",
        "spreadsheet_id": FID,
        "sheet_name": tab,
        "sheet_gid": 728,
        "grid_rows": count,
        "grid_columns": 20,
        "header_row": header,
        "document_type": "quote_request",
        "visible": True,
        "source_access_checked": True,
    }]


class FakeDrive:
    def __init__(self):
        self.revision = "103"
        self.revision_change_after = None
        self.revision_calls = 0
        self.reads = []
        self.swapped = False
        self.broken = False
        self.changed_header = False
        self.changed_boundary = False
        self.max_rows = 500

    def revision_for(self, *, spreadsheet_id):
        assert spreadsheet_id == FID
        self.revision_calls += 1
        if (self.revision_change_after is not None
                and self.revision_calls > self.revision_change_after):
            return {"spreadsheet_id": FID, "revision_kind": DRIVE_VERSION_KIND,
                    "version": "104"}
        return {"spreadsheet_id": FID, "revision_kind": DRIVE_VERSION_KIND,
                "version": self.revision}

    def read(self, *, spreadsheet_id, sheet_name, requested_range,
             value_render_option):
        if self.broken:
            raise RuntimeError("SECRET_FROM_GOOGLE "+FID)
        self.reads.append(requested_range)
        assert spreadsheet_id == FID
        assert value_render_option == "FORMULA"
        first = int(requested_range.split(":")[0][1:])
        last = int(requested_range.split(":")[1][1:])
        rows = []
        for r in range(first,last+1):
            if r == 1:
                rows.append(["商品名" if not self.changed_header else "別名",
                             "JAN", "ASIN", "価格"])
            else:
                rows.append([
                    f"架空商品{r}" if not (self.changed_boundary and r == 196)
                    else "改変された境界商品",
                    JAN if r == 220 else "4901234567894",
                    ASIN if r == 220 else "B0TEST0002",
                    "=1+2" if r == 220 else 800,
                ])
        return {
            "spreadsheet_id": "SYNTHETIC_OTHER_ID" if self.swapped else spreadsheet_id,
            "sheet_name": sheet_name,
            "requested_range": requested_range,
            "value_render_option": value_render_option,
            "rows": rows,
        }


class SupplierScanContinuationTests(unittest.TestCase):
    def run_scan(self, drive, *, cursor=None, private=False, metadata=None,
                 query=None, search=None, ctx=None):
        return scan_next_selected_supplier_sheet(
            supplier_query=query or "架空卸A",
            search=search or {"field":"jan","query":JAN},
            approved_tab_metadata=metadata if metadata is not None else approved(),
            fetch_formula_range=drive.read,
            get_source_revision=drive.revision_for,
            private_cursor=cursor,
            include_private_hits=private,
            reviewer_context=(CONTEXT if ctx is None else ctx) if private else None,
        )

    def test_second_batch_finds_exact_row_220_and_gid_link(self):
        drive = FakeDrive()
        first = self.run_scan(drive)
        self.assertFalse(first["private_cursor"]["complete"])
        self.assertEqual(first["private_cursor"]["next_row"], 197)
        self.assertEqual(first["public_search_summary"]["hits_returned"],0)
        self.assertEqual(first["public_coverage"]["cumulative_data_rows_scanned"],195)
        self.assertEqual(drive.reads,
                         ["A1:O1","A2:O40","A41:O79","A80:O118",
                          "A119:O157","A158:O196"])

        second = self.run_scan(drive,cursor=first["private_cursor"],private=True)
        self.assertEqual(second["public_search_summary"]["hits_returned"],1)
        self.assertEqual(second["public_coverage"]["cumulative_data_rows_scanned"],390)
        self.assertEqual(second["private_cursor"]["next_row"],392)
        self.assertEqual(drive.reads[-7:],
                         ["A1:O1","A196:O196","A197:O235","A236:O274",
                          "A275:O313","A314:O352","A353:O391"])
        hit=second["private_review"]["private_hits"][0]
        self.assertEqual(hit["original_physical_row"],220)
        self.assertEqual(hit["jan_candidate"],JAN)
        self.assertEqual(hit["original_row_url"],
                         "https://docs.google.com/spreadsheets/d/"
                         +FID+"/edit#gid=728&range=A220:O220")
        self.assertTrue(hit["candidate_only"])
        self.assertFalse(hit["purchase_allowed"])

    def test_three_batches_scan_entire_selected_grid_once(self):
        drive=FakeDrive()
        a=self.run_scan(drive)
        b=self.run_scan(drive,cursor=a["private_cursor"])
        c=self.run_scan(drive,cursor=b["private_cursor"])
        self.assertEqual(c["public_coverage"]["cumulative_data_rows_scanned"],499)
        self.assertEqual(c["public_coverage"]["cumulative_hits_lower_bound"],1)
        self.assertTrue(c["private_cursor"]["complete"])
        self.assertTrue(c["public_coverage"]["selected_tab_grid_rows_scanned"])
        self.assertFalse(c["public_coverage"]["all_supplier_folders_searched"])
        self.assertFalse(c["public_coverage"]["other_tabs_searched"])
        with self.assertRaisesRegex(ValueError,"finished"):
            self.run_scan(drive,cursor=c["private_cursor"])

    def test_revision_change_before_resume_fails_without_read(self):
        drive=FakeDrive()
        first=self.run_scan(drive)
        old_reads=len(drive.reads)
        drive.revision="104"
        with self.assertRaisesRegex(ValueError,"revision changed"):
            self.run_scan(drive,cursor=first["private_cursor"])
        self.assertEqual(len(drive.reads),old_reads)

    def test_revision_change_inside_batch_discards_batch(self):
        drive=FakeDrive()
        drive.revision_change_after=1
        with self.assertRaisesRegex(ValueError,"during scan"):
            self.run_scan(drive)
        self.assertEqual(len(drive.reads),6)

    def test_modified_header_rejected_even_if_revision_is_stale(self):
        drive=FakeDrive()
        first=self.run_scan(drive)
        drive.changed_header=True
        with self.assertRaisesRegex(ValueError,"header changed"):
            self.run_scan(drive,cursor=first["private_cursor"])

    def test_modified_previous_row_rejected_even_if_revision_is_stale(self):
        drive=FakeDrive()
        first=self.run_scan(drive)
        drive.changed_boundary=True
        with self.assertRaisesRegex(ValueError,"boundary row changed"):
            self.run_scan(drive,cursor=first["private_cursor"])

    def test_unknown_query_or_metadata_change_blocks_resume(self):
        drive=FakeDrive()
        first=self.run_scan(drive)
        with self.assertRaisesRegex(ValueError,"source or search changed"):
            self.run_scan(drive,cursor=first["private_cursor"],
                          search={"field":"asin","query":ASIN})
        changed=approved()
        changed[0]["sheet_gid"]=729
        with self.assertRaisesRegex(ValueError,"source or search changed"):
            self.run_scan(drive,cursor=first["private_cursor"],metadata=changed)

    def test_forged_cursor_offsets_cannot_skip_rows(self):
        drive=FakeDrive()
        first=self.run_scan(drive)
        for change in [
            {"next_row":300},
            {"scanned_data_rows":True},
            {"source_fingerprint":"a"*64},
            {"complete":True},
            {"new_secret":"token"},
        ]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                cp=deepcopy(first["private_cursor"])
                cp.update(change)
                self.run_scan(drive,cursor=cp)

    def test_broken_revision_witness_rejected_before_fetch(self):
        drive=FakeDrive()
        def incomplete(*,spreadsheet_id):
            return {"spreadsheet_id":spreadsheet_id}
        with self.assertRaisesRegex(ValueError,"Drive v3 file-version evidence"):
            scan_next_selected_supplier_sheet(
                supplier_query="架空卸A",
                search={"field":"jan","query":JAN},
                approved_tab_metadata=approved(),
                fetch_formula_range=drive.read,
                get_source_revision=incomplete)
        self.assertEqual(drive.reads,[])

    def test_broken_connector_errors_redacted(self):
        drive=FakeDrive()
        drive.broken=True
        with self.assertRaises(RuntimeError) as caught:
            self.run_scan(drive)
        self.assertEqual(str(caught.exception),
                         "authorized Sheet range read failed")
        self.assertIsNone(caught.exception.__cause__)

    def test_wrong_file_rejected(self):
        drive=FakeDrive()
        drive.swapped=True
        with self.assertRaisesRegex(ValueError,"wrong-source"):
            self.run_scan(drive)

    def test_private_context_rejected_before_any_read(self):
        drive=FakeDrive()
        with self.assertRaisesRegex(ValueError,"private review"):
            scan_next_selected_supplier_sheet(
                supplier_query="架空卸A",
                search={"field":"jan","query":JAN},
                approved_tab_metadata=approved(),
                fetch_formula_range=drive.read,
                get_source_revision=drive.revision_for,
                include_private_hits=True,
                reviewer_context={})
        self.assertEqual(drive.reads,[])
        self.assertEqual(drive.revision_calls,0)

    def test_multiple_tabs_refused_without_dropping_one(self):
        drive=FakeDrive()
        meta=approved()+[dict(approved()[0],sheet_name="第二タブ",sheet_gid=999)]
        with self.assertRaisesRegex(ValueError,"one selected tab"):
            self.run_scan(drive,metadata=meta)
        self.assertEqual(drive.reads,[])

    def test_safe_public_progress_excludes_private_cursor_and_source(self):
        drive=FakeDrive()
        result=self.run_scan(drive)
        safe=public_scan_progress(result)
        public=json.dumps(safe,ensure_ascii=False)
        for secret in (FID,JAN,ASIN,"架空卸A","架空商品220",
                       "modifiedTime","private_cursor","A197:O235"):
            self.assertNotIn(secret,public)
        self.assertEqual(safe["public_coverage"]["cumulative_data_rows_scanned"],195)
        self.assertFalse(safe["private_details_returned"])

    def test_formula_cells_are_counted_without_execution(self):
        drive=FakeDrive()
        first=self.run_scan(drive)
        self.assertEqual(first["public_summary"]["formula_cells_in_supplied_sheet_windows"],0)
        second=self.run_scan(drive,cursor=first["private_cursor"])
        self.assertEqual(second["public_summary"]["formula_cells_in_supplied_sheet_windows"],1)
        self.assertTrue(second["public_summary"]["formula_cell_values_not_evaluated"])
        self.assertFalse(second["public_summary"]["source_formula_fidelity_verified"])

    def test_header_row_fourteen_continuation(self):
        # Header 14 is supported by the existing parser; test the cursor's
        # precise next-row arithmetic without claiming verified source data.
        drive=FakeDrive()
        def custom(*,spreadsheet_id,sheet_name,requested_range,value_render_option):
            first=int(requested_range.split(":")[0][1:])
            last=int(requested_range.split(":")[1][1:])
            if first==1:
                rows=[[] for _ in range(last-1)] + [["商品名","JAN","ASIN"]]
            else:
                rows=[[f"架空H14{r}",JAN if r==200 else "4901234567894",
                       ASIN] for r in range(first,last+1)]
            drive.reads.append(requested_range)
            return {"spreadsheet_id":spreadsheet_id,"sheet_name":sheet_name,
                    "requested_range":requested_range,
                    "value_render_option":value_render_option,"rows":rows}
        args=dict(supplier_query="架空卸A",
                  search={"field":"jan","query":JAN},
                  approved_tab_metadata=approved(count=300,header=14),
                  fetch_formula_range=custom,
                  get_source_revision=drive.revision_for)
        first=scan_next_selected_supplier_sheet(**args)
        self.assertEqual(first["private_cursor"]["next_row"],145)
        second=scan_next_selected_supplier_sheet(
            **args,private_cursor=first["private_cursor"])
        self.assertEqual(second["public_search_summary"]["hits_returned"],1)
        self.assertIn("A145:O170",drive.reads)
        self.assertEqual(second["private_cursor"]["scanned_data_rows"],260)

    def test_session_does_not_modify_metadata_or_cursor(self):
        drive=FakeDrive()
        meta=approved()
        before=deepcopy(meta)
        a=self.run_scan(drive,metadata=meta)
        saved=deepcopy(a["private_cursor"])
        self.run_scan(drive,cursor=a["private_cursor"],metadata=meta)
        self.assertEqual(meta,before)
        self.assertEqual(a["private_cursor"],saved)


if __name__=="__main__":
    unittest.main()
