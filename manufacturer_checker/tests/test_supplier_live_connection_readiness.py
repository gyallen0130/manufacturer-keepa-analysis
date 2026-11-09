"""Synthetic-only tests for redacted private supplier Reader preflight."""
import json
import unittest
from copy import deepcopy

from supplier_docs.live_connection_readiness import (
    assess_supplier_connection_preflight,
)

REPO = "fictional-operator/private-supplier-knowledge"
EMAIL = "supplier-docs-reader@fictional-project.iam.gserviceaccount.com"
FILES = ("FAKE_GOOGLE_SHEET_00001", "FAKE_GOOGLE_SHEET_00002")


def snapshots():
    return {
        "repo_snapshot": {
            "repository_full_name": REPO,
            "visibility": "private",
            "default_branch": "main",
            "archived": False,
            "id": "10001",
            "owner": {"id": 20002, "type": "User"},
        },
        "branch_snapshot": {"name": "main", "protected": False},
        "selected_file_snapshots": [
            {"id": fid, "mime_type": "application/vnd.google-apps.spreadsheet",
             "permissions": [{"type": "user", "role": "reader",
                              "emailAddress": EMAIL}]}
            for fid in FILES
        ],
        "expected_repo_name": REPO,
        "expected_reader_email": EMAIL,
        "live_workflow_absent": True,
    }


def simulated_cloud_review():
    return {
        "status": "eligible_for_separate_manual_connection_review",
        "checks": {
            "github_private_identity_matches": True,
            "google_oidc_provider_exactly_pinned": True,
            "dedicated_reader_iam_principalset_matches": True,
        },
        "workflow_sha_and_source_commit_pinned": True,
        "actual_oidc_token_exchange_tested": False,
    }


class LiveConnectionReadinessTests(unittest.TestCase):
    def assess(self, **overrides):
        data = snapshots()
        data.update(overrides)
        return assess_supplier_connection_preflight(**data)

    def test_actual_stage_is_no_go_without_cloud_and_billing(self):
        result = self.assess()
        self.assertEqual(result["status"], "blocked_no_live_connection")
        self.assertFalse(result["branch_protected"])
        self.assertTrue(result["checks"]["repo_is_expected_private"])
        self.assertTrue(result["checks"]["dedicated_reader_shared_as_reader_on_all"])
        self.assertFalse(result["checks"]["cloud_provider_and_reader_iam_verified"])
        self.assertFalse(result["checks"]["github_billing_and_stop_control_reviewed"])
        self.assertFalse(result["manual_test_authorized"])
        self.assertIn(
            "unprotected_branch_without_reviewed_cloud_source_pins",
            result["remaining_checks"],
        )

    def test_all_verified_for_separate_review_still_never_authorizes(self):
        result = self.assess(
            observed_cloud_wif_review=simulated_cloud_review(),
            billing_and_stop_control_reviewed=True,
            code_and_dependency_reviewed=True,
        )
        self.assertEqual(result["status"],
                         "eligible_for_separate_owner_manual_test_review")
        self.assertFalse(result["manual_test_authorized"])
        self.assertFalse(result["real_google_oidc_exchange_performed_by_this_check"])
        self.assertTrue(result["branch_risk_mitigated_by_verified_cloud_pins"])

    def test_protected_branch_cannot_replace_unverified_wif(self):
        data = snapshots()
        data["branch_snapshot"]["protected"] = True
        result = self.assess(**data)
        self.assertTrue(result["branch_protected"])
        self.assertFalse(result["checks"]["cloud_provider_and_reader_iam_verified"])
        self.assertEqual(result["status"], "blocked_no_live_connection")

    def test_wrong_repo_or_public_repo_blocked(self):
        for key, value in (
            ("visibility", "public"),
            ("repository_full_name", "other/repo"),
            ("default_branch", "dev"),
            ("archived", True),
            ("id", "not-id"),
        ):
            with self.subTest(key=key):
                data = snapshots()
                data["repo_snapshot"][key] = value
                result = self.assess(**data)
                self.assertFalse(result["checks"]["repo_is_expected_private"])

    def test_missing_or_wrong_reader_permissions_blocked(self):
        for perm in (
            [],
            [{"type": "anyone", "role": "reader", "emailAddress": EMAIL}],
            [{"type": "user", "role": "writer", "emailAddress": EMAIL}],
            [{"type": "user", "role": "reader",
              "emailAddress": "other@fictional-project.iam.gserviceaccount.com"}],
        ):
            with self.subTest(perm=perm):
                data = snapshots()
                data["selected_file_snapshots"][0]["permissions"] = perm
                result = self.assess(**data)
                self.assertFalse(
                    result["checks"]["dedicated_reader_shared_as_reader_on_all"])

    def test_duplicate_file_id_and_unselected_file_rejected(self):
        data = snapshots()
        data["selected_file_snapshots"][1]["id"] = FILES[0]
        result = self.assess(**data)
        self.assertFalse(result["checks"]["two_selected_files_verified"])
        self.assertFalse(result["checks"]["dedicated_reader_shared_as_reader_on_all"])

    def test_missing_branch_protection_evidence_blocks(self):
        result = self.assess(branch_snapshot={"name": "main"})
        self.assertFalse(
            result["checks"]["main_branch_confirmed_unprotected_or_protected"])
        self.assertEqual(result["status"], "blocked_no_live_connection")

    def test_cloud_audit_partial_or_forged_status_does_not_pass(self):
        good = simulated_cloud_review()
        for broken in (
            None, {},
            {**good, "status": "blocked_on_external_configuration_review"},
            {**good, "workflow_sha_and_source_commit_pinned": False},
            {**good, "actual_oidc_token_exchange_tested": True},
            {**good, "checks": {
                **good["checks"], "google_oidc_provider_exactly_pinned": False
            }},
        ):
            with self.subTest(broken=broken):
                result = self.assess(
                    observed_cloud_wif_review=broken,
                    billing_and_stop_control_reviewed=True,
                    code_and_dependency_reviewed=True)
                self.assertEqual(result["status"], "blocked_no_live_connection")

    def test_cloud_pins_without_code_review_still_block_unprotected(self):
        result = self.assess(
            observed_cloud_wif_review=simulated_cloud_review(),
            billing_and_stop_control_reviewed=True,
            code_and_dependency_reviewed=False,
        )
        self.assertIn(
            "unprotected_branch_without_reviewed_cloud_source_pins",
            result["remaining_checks"])

    def test_live_workflow_already_installed_is_not_a_readiness_pass(self):
        result = self.assess(
            live_workflow_absent=False,
            observed_cloud_wif_review=simulated_cloud_review(),
            billing_and_stop_control_reviewed=True,
            code_and_dependency_reviewed=True)
        self.assertFalse(
            result["checks"]["no_live_supplier_workflow_installed"])
        self.assertEqual(result["status"], "blocked_no_live_connection")

    def test_report_never_exposes_private_identifiers(self):
        result = self.assess()
        payload = json.dumps(result, ensure_ascii=False)
        for secret in (REPO, EMAIL, *FILES, "10001", "20002",
                       "fictional-project", "FAKE_GOOGLE"):
            self.assertNotIn(secret, payload)

    def test_input_snapshots_are_not_modified(self):
        data = snapshots()
        original = deepcopy(data)
        self.assess(**data)
        self.assertEqual(data, original)

    def test_invalid_source_count_or_reader_identity_errors(self):
        data = snapshots()
        data["selected_file_snapshots"] = []
        with self.assertRaises(ValueError):
            self.assess(**data)
        data = snapshots()
        data["expected_reader_email"] = "reader@random.invalid"
        with self.assertRaises(ValueError):
            self.assess(**data)


if __name__ == "__main__":
    unittest.main()
