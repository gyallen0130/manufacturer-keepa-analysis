"""Synthetic-only verification of restricted WIF ADC Drive metadata bridge."""
import sys
import types
import unittest
from unittest.mock import patch

from supplier_docs.auth import (
    DRIVE_METADATA_READONLY_SCOPE,
    build_readonly_drive_metadata_service_from_wif_adc,
)
from supplier_docs.supplier_drive_version import (
    FIELDS, DRIVE_VERSION_KIND,
    make_googleapiclient_drive_version_reader,
)

FID = 'SYNTHETIC_DRIVE_METADATA_FILE_001'
MIME = 'application/vnd.google-apps.spreadsheet'


class FakeDriveRequest:
    def __init__(self, *, response, error=None):
        self.response = response
        self.error = error
        self.calls = []
    def execute(self, *, num_retries):
        self.calls.append(num_retries)
        if self.error:
            raise RuntimeError(self.error)
        return self.response


class FakeDriveV3:
    def __init__(self, *, response=None, error=None):
        self.requests = []
        self.reply = FakeDriveRequest(response=response, error=error)
    def files(self):
        return self
    def get(self, *, fileId, fields, supportsAllDrives):
        self.requests.append((fileId, fields, supportsAllDrives))
        return self.reply


class VersionBridgeTests(unittest.TestCase):
    def test_raw_drive_client_uses_three_metadata_fields_only(self):
        api = FakeDriveV3(response={
            'id': FID,'mimeType':MIME,'version':'9007199254740993'
        })
        reader = make_googleapiclient_drive_version_reader(api)
        value = reader(spreadsheet_id=FID)
        self.assertEqual(value['version'],'9007199254740993')
        self.assertEqual(value['revision_kind'],DRIVE_VERSION_KIND)
        self.assertEqual(api.requests,[(FID,FIELDS,True)])
        self.assertEqual(api.reply.calls,[0])

    def test_absent_version_fails_closed_with_no_timestamp_fallback(self):
        api = FakeDriveV3(response={
            'id':FID,'mimeType':MIME,'modifiedTime':'2026-11-09T00:00:00Z'
        })
        reader = make_googleapiclient_drive_version_reader(api)
        with self.assertRaisesRegex(ValueError,'raw version metadata'):
            reader(spreadsheet_id=FID)

    def test_wrong_file_mime_and_extra_fields_are_rejected(self):
        for response in (
            {'id':'SYNTHETIC_OTHER_FILE_002','mimeType':MIME,'version':'3'},
            {'id':FID,'mimeType':'application/vnd.google-apps.document','version':'3'},
            {'id':FID,'mimeType':MIME,'version':'3','parents':[]},
            {'id':FID,'mimeType':MIME,'version':1.0},
        ):
            with self.subTest(response=response):
                api=FakeDriveV3(response=response)
                with self.assertRaises(ValueError):
                    make_googleapiclient_drive_version_reader(api)(
                        spreadsheet_id=FID)

    def test_api_error_redacted_without_chaining_token(self):
        api = FakeDriveV3(error='SECRET_ACCESS_TOKEN '+FID)
        with self.assertRaises(RuntimeError) as caught:
            make_googleapiclient_drive_version_reader(api)(spreadsheet_id=FID)
        self.assertEqual(str(caught.exception),
                         'authorized Drive version read failed')
        self.assertIsNone(caught.exception.__cause__)

    def test_incorrect_api_or_invalid_file_id_fail_without_request(self):
        for invalid in (None,{},'not api'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                make_googleapiclient_drive_version_reader(invalid)
        api=FakeDriveV3(response={'id':FID,'mimeType':MIME,'version':'1'})
        with self.assertRaises(ValueError):
            make_googleapiclient_drive_version_reader(api)(
                spreadsheet_id='invalid/id')
        self.assertEqual(api.requests,[])

    def test_wif_adc_uses_metadata_readonly_scope_and_drive_v3_only(self):
        captured={}
        google=types.ModuleType('google')
        google.__path__=[]
        auth=types.ModuleType('google.auth')
        def default(*,scopes):
            captured['scopes']=scopes
            return object(), 'project'
        auth.default=default
        google.auth=auth
        googleapiclient=types.ModuleType('googleapiclient')
        googleapiclient.__path__=[]
        discovery=types.ModuleType('googleapiclient.discovery')
        expected_client=object()
        def build(service,version,*,credentials,cache_discovery):
            captured['build']=(service,version,cache_discovery)
            captured['credentials']=credentials
            return expected_client
        discovery.build=build
        with patch.dict(sys.modules, {
            'google':google,'google.auth':auth,
            'googleapiclient':googleapiclient,
            'googleapiclient.discovery':discovery,
        }):
            client=build_readonly_drive_metadata_service_from_wif_adc()
        self.assertIs(client,expected_client)
        self.assertEqual(captured['scopes'],[DRIVE_METADATA_READONLY_SCOPE])
        self.assertEqual(captured['build'],('drive','v3',False))


if __name__=='__main__':
    unittest.main()
