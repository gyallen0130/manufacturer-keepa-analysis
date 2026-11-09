"""No-network tests for the PRIVATE owner metadata-only version check."""
import json
import unittest

from supplier_docs.manual_drive_version_probe import (
    main, run_version_probe,
)

FID = 'SYNTHETIC_APPROVED_SHEET_ID_001'
MIME = 'application/vnd.google-apps.spreadsheet'


class Service:
    def __init__(self, version='18', error=None):
        self.version = version
        self.error = error
        self.calls = []
    def files(self):
        return self
    def get(self, *, fileId, fields, supportsAllDrives):
        self.calls.append((fileId,fields,supportsAllDrives))
        return self
    def execute(self, *, num_retries):
        if self.error:
            raise RuntimeError('private OAuth '+FID)
        return {'id':FID,'mimeType':MIME,'version':self.version}


class ManualVersionProbeTests(unittest.TestCase):
    def test_one_approved_file_metadata_only_and_redacted(self):
        service=Service()
        ret=run_version_probe(confirmed=True,file_id=FID,
                              service_factory=lambda:service)
        self.assertEqual(ret['status'],'raw_drive_v3_monotonic_version_available')
        self.assertEqual(service.calls,[(FID,'id,mimeType,version',True)])
        self.assertFalse(ret['sheet_cells_read'])
        public=json.dumps(ret)
        self.assertNotIn(FID,public)
        self.assertNotIn('18',public)
        self.assertFalse(ret['wif_provider_verified_by_probe'])

    def test_no_confirmation_blocks_before_service_construction(self):
        called=[]
        with self.assertRaises(ValueError):
            run_version_probe(
                confirmed=False,file_id=FID,
                service_factory=lambda:called.append(True))
        self.assertFalse(called)

    def test_absent_file_id_blocks_before_service_construction(self):
        called=[]
        for invalid in (None,'','wrong/id','abc\nmalformed'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                run_version_probe(
                    confirmed=True,file_id=invalid,
                    service_factory=lambda:called.append(True))
        self.assertFalse(called)

    def test_cli_missing_confirm_is_never_live(self):
        called=[]
        output=[]
        ret=main([],environ={'SUPPLIER_APPROVED_SHEET_ID':FID},
                 service_factory=lambda:called.append(True),output=output.append)
        self.assertEqual(ret,1)
        self.assertEqual(called,[])
        self.assertEqual(len(output),1)
        self.assertEqual(json.loads(output[0])['status'],
                         'blocked_version_or_auth_unavailable')

    def test_cli_success_does_not_report_version_file_or_supplier(self):
        output=[]
        ret=main(['--confirm-readonly'],
                 environ={'SUPPLIER_APPROVED_SHEET_ID':FID},
                 service_factory=lambda:Service(version='109'),
                 output=output.append)
        self.assertEqual(ret,0)
        payload=json.loads(output[0])
        self.assertEqual(payload['status'],
                         'raw_drive_v3_monotonic_version_available')
        self.assertNotIn(FID,output[0])
        self.assertNotIn('109',output[0])

    def test_sdk_error_masked_without_traceback(self):
        output=[]
        ret=main(['--confirm-readonly'],
                 environ={'SUPPLIER_APPROVED_SHEET_ID':FID},
                 service_factory=lambda:Service(error='auth'),
                 output=output.append)
        self.assertEqual(ret,1)
        self.assertNotIn(FID,output[0])
        self.assertNotIn('OAuth',output[0])
        self.assertEqual(json.loads(output[0])['status'],
                         'blocked_version_or_auth_unavailable')

    def test_missing_drive_version_masks_details(self):
        output=[]
        ret=main(['--confirm-readonly'],
                 environ={'SUPPLIER_APPROVED_SHEET_ID':FID},
                 service_factory=lambda:Service(version=None),
                 output=output.append)
        self.assertEqual(ret,1)
        self.assertNotIn(FID,output[0])
        self.assertNotIn('None',output[0])


if __name__ == '__main__':
    unittest.main()
