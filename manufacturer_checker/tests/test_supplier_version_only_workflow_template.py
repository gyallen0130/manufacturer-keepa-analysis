"""Synthetic/static safety tests for NOT INSTALLED private version-only WIF template.

These assertions cannot verify actual Cloud IAM, GitHub Billing, action source
security, user authorization, or the correctness of a running GitHub workflow.
"""
import re
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] /
          "supplier_docs" / "templates" / "version-only" /
          "supplier-readonly.yml")


class VersionOnlyWorkflowTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = SOURCE.read_text(encoding="utf-8")

    def test_template_is_not_in_live_github_workflows_path(self):
        self.assertIn("/templates/version-only/", str(SOURCE).replace("\\", "/"))
        self.assertIn("TEMPLATE ONLY", self.workflow)
        self.assertIn("NOT installed anywhere", self.workflow)

    def test_only_manual_trigger_declared(self):
        text = self.workflow
        self.assertRegex(text, r"(?m)^on:\s*\n\s+workflow_dispatch:\s*$")
        for denied in ("schedule:", "push:", "pull_request:",
                       "pull_request_target:", "workflow_run:",
                       "repository_dispatch:"):
            self.assertNotIn(denied, text)

    def test_private_repo_main_ref_manual_runtime_guards(self):
        for required in (
            "github.event_name == 'workflow_dispatch'",
            "github.ref == 'refs/heads/main'",
            "github.event.repository.private == true",
        ):
            self.assertIn(required, self.workflow)

    def test_timeout_and_concurrency_are_bounded(self):
        self.assertRegex(self.workflow, r"(?m)^\s+timeout-minutes: 3$")
        self.assertIn("cancel-in-progress: false", self.workflow)
        self.assertIn("supplier-manual-version-only", self.workflow)

    def test_id_token_write_only_at_job_with_no_other_write_grants(self):
        x = self.workflow
        self.assertEqual(x.count("id-token: write"), 1)
        self.assertGreaterEqual(x.count("contents: read"), 2)
        for forbidden in ("contents: write", "actions: write",
                          "pull-requests: write", "write-all",
                          "security-events: write"):
            self.assertNotIn(forbidden, x)

    def test_all_actions_pinned_to_full_commit_sha(self):
        refs = re.findall(r"(?m)^\s+uses: (\S+)$", self.workflow)
        self.assertEqual(len(refs), 3)
        for ref in refs:
            self.assertRegex(ref, r"^[A-Za-z0-9_-]+/[A-Za-z0-9_-]+@[0-9a-f]{40}$")
        self.assertIn("actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
                      refs)
        self.assertIn("google-github-actions/auth@7c6bc770dae815cd3e89ee6cdf493a5fab2cc093",
                      refs)

    def test_no_persistent_checkout_github_credentials(self):
        self.assertIn("persist-credentials: false", self.workflow)

    def test_no_contents_or_price_manifest_read(self):
        for denied in ("SUPPLIER_READ_MANIFEST_JSON", "manual_sheet_probe",
                       "sheets.readonly", "spreadsheets.values",
                       "get_spreadsheet_range", "profit", "price"):
            self.assertNotIn(denied, self.workflow)

    def test_no_artifact_or_implicit_file_upload(self):
        for denied in ("upload-artifact", "download-artifact",
                       "artifact:", "curl ", "wget ", "tee ",
                       ">>", "store-artifact"):
            self.assertNotIn(denied, self.workflow)

    def test_exact_one_source_id_and_two_wif_vars(self):
        self.assertIn("SUPPLIER_APPROVED_SHEET_ID: ${{ secrets.SUPPLIER_APPROVED_SHEET_ID }}",
                      self.workflow)
        self.assertIn("workload_identity_provider: ${{ vars.SUPPLIER_WIF_PROVIDER }}",
                      self.workflow)
        self.assertIn("service_account: ${{ vars.SUPPLIER_READER_SA }}",
                      self.workflow)
        self.assertNotIn("GOOGLE_APPLICATION_CREDENTIALS:", self.workflow)

    def test_hash_locked_binary_only_dependencies(self):
        for required in ("--require-hashes", "--only-binary=:all:",
                         "approved-requirements-hashed.txt",
                         "python -m pip check"):
            self.assertIn(required, self.workflow)

    def test_only_probe_python_module_is_invoked(self):
        self.assertEqual(self.workflow.count(
            "python -m supplier_docs.manual_drive_version_probe --confirm-readonly"), 1)
        self.assertNotIn("python -m supplier_docs.manual_sheet_probe", self.workflow)

    def test_template_warns_about_unverified_cost_and_wif(self):
        for required in ("billing/stop controls",
                         "reviewed workflow SHA",
                         "NOT installed anywhere"):
            self.assertIn(required,self.workflow)

    def test_no_shell_interpolation_of_untrusted_workflow_input(self):
        self.assertNotIn("github.event.inputs", self.workflow)
        self.assertNotIn("toJSON(", self.workflow)


if __name__ == "__main__":
    unittest.main()
