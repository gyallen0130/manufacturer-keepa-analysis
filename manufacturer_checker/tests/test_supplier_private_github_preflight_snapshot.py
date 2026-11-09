"""Synthetic only: authenticated GitHub connector -> WIF preflight schema."""
from copy import deepcopy
import json
import unittest

from supplier_docs.private_github_preflight_snapshot import (
    private_github_repo_wif_snapshot,
    redacted_github_wif_snapshot_summary,
)

NAME = "fictional-owner/private-supplier-repo"


def observed():
    return {
        "repository_full_name": NAME,
        "id": "987654321",
        "visibility": "private",
        "default_branch": "main",
        "archived": False,
        "owner": {"id": 123456789, "type": "User"},
        "permissions": {"admin": True, "push": True, "pull": True},
    }


def branch():
    return {"name": "main", "protected": False}


class GithubWifSnapshotTests(unittest.TestCase):
    def snapshot(self, repo=None, main_branch=None, expected_repo=NAME):
        return private_github_repo_wif_snapshot(
            repo=observed() if repo is None else repo,
            main_branch=branch() if main_branch is None else main_branch,
            expected_repo=expected_repo,
        )

    def test_connected_github_field_names_convert_to_audit_contract(self):
        result=self.snapshot()
        self.assertEqual(result, {
            "id":"987654321",
            "owner":{"id":123456789},
            "full_name":NAME,
            "visibility":"private",
            "default_branch":"main",
            "archived":False,
            "default_branch_protected":False,
        })

    def test_redacted_report_has_no_user_or_repo_identifiers(self):
        report=redacted_github_wif_snapshot_summary(self.snapshot())
        plain=json.dumps(report)
        for secret in (NAME,"fictional-owner","987654321","123456789"):
            self.assertNotIn(secret,plain)
        self.assertTrue(report["private_repository_observed"])
        self.assertFalse(report["branch_protection_enabled"])
        self.assertFalse(report["production_connection_authorized"])
        self.assertFalse(report["google_wif_provider_verified"])

    def test_expected_repo_name_mismatch_fails(self):
        with self.assertRaisesRegex(ValueError,"repository identity"):
            self.snapshot(expected_repo="other-owner/other-private")

    def test_missing_admin_permission_fails(self):
        r=observed()
        r["permissions"]["admin"]=False
        with self.assertRaises(ValueError):
            self.snapshot(repo=r)

    def test_public_archived_or_wrong_branch_fails(self):
        for name,value in (("visibility","public"),("archived",True),
                           ("default_branch","develop")):
            with self.subTest(name=name):
                r=observed()
                r[name]=value
                with self.assertRaises(ValueError):
                    self.snapshot(repo=r)

    def test_rejects_bad_stable_identity_formats(self):
        for value in (1,True,None,"0","001","1;rm -rf /","abc", ""):
            with self.subTest(value=value):
                r=observed()
                r["id"]=value
                with self.assertRaises(ValueError):
                    self.snapshot(repo=r)
        for value in ("123",True,0,-1,None):
            with self.subTest(owner=value):
                r=observed()
                r["owner"]["id"]=value
                with self.assertRaises(ValueError):
                    self.snapshot(repo=r)

    def test_branch_missing_or_protection_unverified_fails(self):
        for observed_branch in ({}, {"name":"other","protected":False},
                                {"name":"main","protected":None},
                                {"name":"main","protected":"false"}):
            with self.subTest(branch=observed_branch):
                with self.assertRaises(ValueError):
                    self.snapshot(main_branch=observed_branch)

    def test_true_protection_kept_not_assumed(self):
        result=self.snapshot(main_branch={"name":"main","protected":True})
        self.assertTrue(result["default_branch_protected"])

    def test_owner_org_may_be_supported(self):
        r=observed()
        r["owner"]["type"]="Organization"
        self.assertEqual(self.snapshot(repo=r)["owner"]["id"],123456789)

    def test_inputs_not_modified(self):
        r=observed()
        b=branch()
        original=deepcopy((r,b))
        self.snapshot(repo=r,main_branch=b)
        self.assertEqual((r,b),original)

    def test_bad_redaction_inputs_rejected(self):
        for value in (None, {}, {"id":"123"}, {"id":"a","owner":{"id":1}},
                      {**self.snapshot(),"secret":"real"}):
            with self.subTest(value=value),self.assertRaises(ValueError):
                redacted_github_wif_snapshot_summary(value)


if __name__=="__main__":
    unittest.main()
