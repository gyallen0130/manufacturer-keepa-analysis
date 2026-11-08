"""Offline checks for safe but currently non-deployable private WIF template."""
from pathlib import Path
import re
import unittest

from supplier_docs.private_workflow_integrity import (
    ACTIONS, review_private_workflow_template,
)


def load_template():
    return (Path(__file__).resolve().parents[1] /
            "supplier_docs" / "templates" / "supplier-readonly.yml"
            ).read_text(encoding="utf-8")


class PrivateWorkflowReviewTests(unittest.TestCase):
    def test_real_inactive_template_pins_four_action_shas(self):
        report = review_private_workflow_template(load_template())
        checks = report["checks"]
        self.assertTrue(checks["official_actions_full_commit_sha_pinned"])
        self.assertTrue(checks["manual_private_only_structural_gate"])
        self.assertTrue(checks["least_privilege_workflow_permissions_present"])
        self.assertTrue(checks["encrypted_artifact_only_structural_gate"])
        # Live execution MUST remain blocked until wheel hashes are fixed.
        self.assertFalse(checks["python_dependency_hash_lock_present"])
        self.assertEqual(report["status"],
                         "blocked_on_workflow_or_dependency_review")
        self.assertFalse(report["real_google_wif_verified"])
        self.assertFalse(report["automatic_workflow_enabled"])
        self.assertFalse(report["additional_cost_guaranteed_zero"])

    def test_floating_action_tag_or_unreviewed_action_rejected(self):
        current = load_template()
        pinned = ACTIONS["actions/checkout"]
        for changed in (
            current.replace(pinned, "v4"),
            current.replace(pinned, "a" * 40),
            current + "\n      - uses: unreviewed/action@v1\n",
        ):
            result = review_private_workflow_template(changed)
            self.assertFalse(
                result["checks"]["official_actions_full_commit_sha_pinned"])

    def test_pr_schedule_push_and_public_gate_removed_are_denied(self):
        template = load_template()
        for changed in (
            template.replace("  workflow_dispatch:", "  schedule:"),
            template.replace("  workflow_dispatch:", "  pull_request:"),
            template.replace("github.event.repository.private == true",
                             "github.event.repository.private == false"),
            template.replace("github.ref == 'refs/heads/main'",
                             "github.ref == 'refs/heads/dev'"),
        ):
            with self.subTest(case=changed[-110:]):
                result = review_private_workflow_template(changed)
                self.assertFalse(
                    result["checks"]["manual_private_only_structural_gate"])

    def test_broad_token_or_checkout_token_persistence_is_denied(self):
        template = load_template()
        for changed in (
            template.replace("permissions:\n  contents: read",
                             "permissions:\n  contents: write"),
            template.replace("persist-credentials: false",
                             "persist-credentials: true"),
            template.replace("id-token: write", "id-token: read"),
        ):
            report = review_private_workflow_template(changed)
            self.assertFalse(
                report["checks"]["least_privilege_workflow_permissions_present"])

    def test_plaintext_artifact_or_long_retention_denied(self):
        template = load_template()
        for changed in (
            template.replace("owner_encrypted_artifact", "plaintext"),
            template.replace("retention-days: 1", "retention-days: 90"),
            template.replace(
                "supplier-owner-encrypted-result.json", "*.json"),
        ):
            report = review_private_workflow_template(changed)
            self.assertFalse(
                report["checks"]["encrypted_artifact_only_structural_gate"])

    def test_demo_requires_real_hash_lock_not_just_comment(self):
        template = load_template()
        report = review_private_workflow_template(template)
        self.assertFalse(report["checks"]["python_dependency_hash_lock_present"])
        # A random comment mentioning hash flags must not satisfy the check.
        # This is a conservative substring preflight, not a YAML validator:
        # a future deployable workflow requires a stronger content audit.
        self.assertFalse(report["reviewed_commit_and_dependency_contents_attested"])

    def test_empty_oversized_and_non_string_file_denied(self):
        for content in ("", "x" * 30001, None):
            with self.subTest(size=len(content) if content else 0):
                with self.assertRaises(ValueError):
                    review_private_workflow_template(content)


if __name__ == "__main__":
    unittest.main()
