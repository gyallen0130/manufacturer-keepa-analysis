"""Offline tests: Google Drive v3 monotonic version, not timestamp or revisions."""
import unittest

from supplier_docs.supplier_drive_version import (
    DRIVE_VERSION_KIND, FIELDS, GOOGLE_SHEET_MIME,
    strict_drive_v3_version, strict_revision_evidence,
    make_drive_v3_version_adapter,
)
from supplier_docs.supplier_scan_continuation import scan_next_selected_supplier_sheet

FID = 'SYNTHETIC_DRIVE_VERSION_FILE_001'


def raw(version='105', file_id=FID, mime=GOOGLE_SHEET_MIME):
    return {'id':file_id, 'mimeType':mime, 'version':version}


class DriveVersionTests(unittest.TestCase):
    def test_valid_google_file_version_evidence(self):
        result=strict_drive_v3_version(
            metadata=raw('9223372036854775807'),expected_file_id=FID)
        self.assertEqual(result, {
            'spreadsheet_id':FID,
            'revision_kind':DRIVE_VERSION_KIND,
            'version':'9223372036854775807',
        })
        self.assertEqual(
            strict_revision_evidence(evidence=result,expected_file_id=FID),
            '9223372036854775807')

    def test_raw_reader_receives_exact_file_id_and_requested_fields(self):
        calls=[]
        def metadata(*,file_id,fields):
            calls.append((file_id,fields))
            return raw('107',file_id)
        reader=make_drive_v3_version_adapter(metadata)
        result=reader(spreadsheet_id=FID)
        self.assertEqual(calls,[(FID,'id,mimeType,version')])
        self.assertEqual(FIELDS,'id,mimeType,version')
        self.assertEqual(result['version'],'107')

    def test_missing_or_non_numeric_google_version_rejected(self):
        for version in (None,105,True,0,-1,'','0','00','0105',
                        '105.0','1e2',' 105','105\n','+105',
                        '18446744073709551615',
                        '9223372036854775808'):
            with self.subTest(version=version),self.assertRaises(ValueError):
                strict_drive_v3_version(
                    metadata=raw(version),expected_file_id=FID)

    def test_wrong_document_identity_and_mime_rejected(self):
        for meta in (
            raw('101', file_id='SYNTHETIC_OTHER_FILE_000'),
            raw('101', mime='application/vnd.google-apps.document'),
            raw('101', mime='application/vnd.ms-excel'),
        ):
            with self.subTest(meta=meta), self.assertRaises(ValueError):
                strict_drive_v3_version(metadata=meta,expected_file_id=FID)

    def test_missing_or_extra_fields_rejected(self):
        for meta in (
            {'id':FID,'mimeType':GOOGLE_SHEET_MIME},
            {**raw(),'modifiedTime':'2026-11-09T06:00:00Z'},
            {'id':FID,'mimeType':GOOGLE_SHEET_MIME,
             'modifiedTime':'2026-11-09T06:00:00Z'},
            {'id':FID,'mimeType':GOOGLE_SHEET_MIME,
             'currentRevisionId':'1234'},
            {'id':FID,'mimeType':GOOGLE_SHEET_MIME,'revision':'1234'},
        ):
            with self.subTest(meta=meta),self.assertRaises(ValueError):
                strict_drive_v3_version(
                    metadata=meta,expected_file_id=FID)

    def test_metadata_connector_projected_shape_not_mistaken_for_raw_api(self):
        # ChatGPT's current Google Drive metadata connector includes
        # modified_time but not the Drive v3 version.
        projected={'id':FID,'title':'架空資料',
                   'mime_type':GOOGLE_SHEET_MIME,
                   'modified_time':'2026-11-09T06:00:00Z'}
        with self.assertRaisesRegex(ValueError,'raw version metadata'):
            strict_drive_v3_version(
                metadata=projected,expected_file_id=FID)

    def test_typed_witness_must_have_correct_version_kind_and_id(self):
        good=strict_drive_v3_version(
            metadata=raw(),expected_file_id=FID)
        for changed in (
            {**good,'revision_kind':'modifiedTime'},
            {**good,'revision_kind':'latest_revisions_list_id'},
            {**good,'spreadsheet_id':'SYNTHETIC_OTHER_FILE_000'},
            {**good,'source_file':'unexpected'},
            {**good,'version':'2026-11-09T06:00:00Z'},
            {**good,'version':True},
        ):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                strict_revision_evidence(
                    evidence=changed,expected_file_id=FID)

    def test_reader_failure_redacts_sensitive_source_and_does_not_chain(self):
        def bad(**kwargs):
            raise RuntimeError('OAuthSecret '+FID)
        get_revision=make_drive_v3_version_adapter(bad)
        with self.assertRaises(RuntimeError) as exception:
            get_revision(spreadsheet_id=FID)
        self.assertEqual(str(exception.exception),
                         'authorized Drive version read failed')
        self.assertIsNone(exception.exception.__cause__)

    def test_missing_get_callback_rejected(self):
        with self.assertRaises(ValueError):
            make_drive_v3_version_adapter(None)

    def test_drive_v3_version_change_stops_scan_on_resume(self):
        document=FID
        row_count=220
        state={'version':'8'}
        metadata=[{
            'supplier_label':'架空版管理',
            'spreadsheet_id':document,
            'sheet_name':'見積',
            'sheet_gid':0,
            'grid_rows':row_count,
            'grid_columns':15,
            'header_row':1,
            'document_type':'quote_request',
            'visible':True,
            'source_access_checked':True,
        }]
        calls=[]
        def get_raw(*,file_id,fields):
            return raw(state['version'],file_id)
        adapter=make_drive_v3_version_adapter(get_raw)
        def read(*,spreadsheet_id,sheet_name,requested_range,value_render_option):
            calls.append(requested_range)
            start,end=requested_range.split(':')
            first,last=int(start[1:]),int(end[1:])
            rows=([['商品名','JAN','ASIN']]
                  if first==1 else
                  [[f'架空部品{r}','4901234567894','B0TEST0001']
                   for r in range(first,last+1)])
            return {'spreadsheet_id':spreadsheet_id,
                    'sheet_name':sheet_name,
                    'requested_range':requested_range,
                    'value_render_option':value_render_option,
                    'rows':rows}
        args=dict(supplier_query='架空版管理',
                  search={'field':'jan','query':'0000000000017'},
                  approved_tab_metadata=metadata,
                  fetch_formula_range=read,
                  get_source_revision=adapter)
        first=scan_next_selected_supplier_sheet(**args)
        self.assertEqual(first['private_cursor']['next_row'],197)
        count=len(calls)
        state['version']='9'
        with self.assertRaisesRegex(ValueError,'revision changed'):
            scan_next_selected_supplier_sheet(
                **args,private_cursor=first['private_cursor'])
        self.assertEqual(len(calls),count)

    def test_bare_timestamp_style_revision_reader_rejected_before_cells(self):
        cells=[]
        metadata=[{
            'supplier_label':'架空版管理',
            'spreadsheet_id':FID,'sheet_name':'見積',
            'sheet_gid':0,'grid_rows':40,'grid_columns':15,
            'header_row':1,'document_type':'quote_request',
            'visible':True,'source_access_checked':True,
        }]
        def read(**kwargs):
            cells.append(kwargs)
            raise AssertionError('should not read')
        def legacy(*,spreadsheet_id):
            return {'spreadsheet_id':spreadsheet_id,
                    'revision':'2026-11-09T06:00:00Z'}
        with self.assertRaisesRegex(ValueError,'Drive v3 file-version'):
            scan_next_selected_supplier_sheet(
                supplier_query='架空版管理',
                search={'field':'jan','query':'0000000000017'},
                approved_tab_metadata=metadata,
                fetch_formula_range=read,
                get_source_revision=legacy)
        self.assertEqual(cells,[])


if __name__ == '__main__':
    unittest.main()
