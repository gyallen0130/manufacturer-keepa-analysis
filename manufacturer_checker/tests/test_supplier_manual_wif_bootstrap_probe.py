"""Synthetic no-network checks for preliminary gcloud WIF Reader presence."""
import json
import unittest
from types import SimpleNamespace

from supplier_docs.manual_wif_bootstrap_probe import (
    inspect_wif_bootstrap_readonly, main,
)

PROVIDER=("projects/123456789012/locations/global/"
          "workloadIdentityPools/fictional-pool/"
          "providers/fictional-provider")
READER="supplier-docs-reader@fictional-project.iam.gserviceaccount.com"


def fixtures():
    provider = {
        "name": PROVIDER,
        "state": "ACTIVE",
        "disabled": False,
        "oidc": {"issuerUri": "https://token.actions.githubusercontent.com"},
        "attributeMapping": {
            "attribute.repository_id":"assertion.repository_id",
            "attribute.repository_owner_id":"assertion.repository_owner_id",
            "attribute.workflow_sha":"assertion.workflow_sha",
            "attribute.sha":"assertion.sha",
        },
        "attributeCondition":"assertion.repository_visibility=='private'",
    }
    policy = {"bindings":[{
        "role":"roles/iam.workloadIdentityUser",
        "members":["principalSet://iam.googleapis.com/projects/123456789012/"
                   "locations/global/workloadIdentityPools/fictional-pool/"
                   "attribute.repository_id/987654"],
    }]}
    return provider, policy


class FakeGcloud:
    def __init__(self, payloads=None, exit_code=0):
        self.payloads = fixtures() if payloads is None else payloads
        self.exit_code = exit_code
        self.calls = []
    def __call__(self, argv):
        self.calls.append(tuple(argv))
        index=len(self.calls)-1
        return SimpleNamespace(returncode=self.exit_code,
                               stdout=json.dumps(self.payloads[index]),
                               stderr="PRIVATE_OAUTH_OR_RESOURCE_PATH")


class BootstrapProbeTests(unittest.TestCase):
    def inspect(self, fake=None, **kwargs):
        return inspect_wif_bootstrap_readonly(
            provider_resource=PROVIDER,
            reader_service_account=READER,
            owner_approved_readonly=True,
            executor=FakeGcloud() if fake is None else fake,
            **kwargs)

    def test_only_two_expected_readonly_commands(self):
        fake=FakeGcloud()
        result=self.inspect(fake)
        self.assertEqual(len(fake.calls),2)
        self.assertEqual(fake.calls[0][:5],
                         ("gcloud","iam","workload-identity-pools",
                          "providers","describe"))
        self.assertEqual(fake.calls[1][:4],
                         ("gcloud","iam","service-accounts","get-iam-policy"))
        for argv in fake.calls:
            self.assertIn("--format=json",argv)
            self.assertNotIn("create",argv)
            self.assertNotIn("set-iam-policy",argv)
            self.assertNotIn("add-iam-policy-binding",argv)
        self.assertTrue(all(result["checks"].values()))
        self.assertFalse(result["strict_wif_provider_condition_verified"])
        self.assertFalse(result["production_connection_authorized"])

    def test_redacted_report_never_contains_identifiers(self):
        result=self.inspect()
        payload=json.dumps(result)
        for forbidden in (PROVIDER,READER,"fictional-provider",
                          "fictional-project","123456789012","987654",
                          "PRIVATE_OAUTH"):
            self.assertNotIn(forbidden,payload)

    def test_no_owner_confirmation_stops_before_command(self):
        fake=FakeGcloud()
        with self.assertRaises(PermissionError):
            inspect_wif_bootstrap_readonly(
                provider_resource=PROVIDER,
                reader_service_account=READER,
                owner_approved_readonly=False,executor=fake)
        self.assertEqual(fake.calls,[])

    def test_invalid_provider_or_reader_stops_before_command(self):
        fake=FakeGcloud()
        for a,b in (("invalid",READER),
                    (PROVIDER,"admin@untrusted.invalid"),
                    (PROVIDER+"\n--quiet",READER)):
            with self.subTest(a=a,b=b),self.assertRaises(ValueError):
                inspect_wif_bootstrap_readonly(
                    provider_resource=a,reader_service_account=b,
                    owner_approved_readonly=True,executor=fake)
        self.assertEqual(fake.calls,[])

    def test_provider_inactive_rejects_without_approval(self):
        p,iam=fixtures()
        p["state"]="DISABLED"
        result=self.inspect(FakeGcloud((p,iam)))
        self.assertFalse(result["checks"]["provider_reports_active"])
        self.assertFalse(result["production_connection_authorized"])

    def test_bad_oidc_issuer_does_not_approve(self):
        p,iam=fixtures()
        p["oidc"]["issuerUri"]="https://untrusted.example"
        result=self.inspect(FakeGcloud((p,iam)))
        self.assertFalse(result["checks"]["github_oidc_issuer_observed"])

    def test_missing_critical_mapping_does_not_approve(self):
        p,iam=fixtures()
        del p["attributeMapping"]["attribute.sha"]
        result=self.inspect(FakeGcloud((p,iam)))
        self.assertFalse(result["checks"]["required_claim_mappings_present"])

    def test_missing_workload_binding_does_not_approve(self):
        p,iam=fixtures()
        iam["bindings"]=[]
        result=self.inspect(FakeGcloud((p,iam)))
        self.assertFalse(result["checks"]["some_workload_identity_user_grant_present"])

    def test_cli_missing_confirmation_fails_with_no_gcloud(self):
        fake=FakeGcloud()
        emitted=[]
        code=main([],
                  environ={"SUPPLIER_WIF_PROVIDER":PROVIDER,
                           "SUPPLIER_READER_SA":READER},
                  executor=fake,output=emitted.append)
        self.assertEqual(code,1)
        self.assertEqual(fake.calls,[])
        self.assertEqual(json.loads(emitted[0])["status"],
                         "blocked_cloud_bootstrap_not_verified")
        self.assertNotIn(PROVIDER,emitted[0])

    def test_cli_success_yet_connection_not_authorized(self):
        fake=FakeGcloud()
        emitted=[]
        code=main(["--confirm-readonly"],
                  environ={"SUPPLIER_WIF_PROVIDER":PROVIDER,
                           "SUPPLIER_READER_SA":READER},
                  executor=fake,output=emitted.append)
        self.assertEqual(code,0)
        result=json.loads(emitted[0])
        self.assertFalse(result["production_connection_authorized"])
        self.assertEqual(result["status"],
                         "bootstrap_evidence_collected_not_approved")
        self.assertNotIn(READER,emitted[0])

    def test_failed_command_hides_stderr(self):
        fake=FakeGcloud(exit_code=1)
        emitted=[]
        code=main(["--confirm-readonly"],
                  environ={"SUPPLIER_WIF_PROVIDER":PROVIDER,
                           "SUPPLIER_READER_SA":READER},
                  executor=fake,output=emitted.append)
        self.assertEqual(code,1)
        self.assertNotIn("PRIVATE_OAUTH",emitted[0])
        self.assertNotIn(PROVIDER,emitted[0])

    def test_preliminary_check_never_approves_weak_provider_condition(self):
        p,iam=fixtures()
        p["attributeCondition"]="true"
        result=self.inspect(FakeGcloud((p,iam)))
        self.assertTrue(result["checks"]["provider_metadata_readable"])
        self.assertFalse(result["strict_wif_provider_condition_verified"])
        self.assertFalse(result["production_connection_authorized"])


if __name__=="__main__":
    unittest.main()
