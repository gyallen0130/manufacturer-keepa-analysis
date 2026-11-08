"""Synthetic gcloud only: verify read-only commands and no credential leak."""
import json
from types import SimpleNamespace
import subprocess
import unittest

from supplier_docs.gcloud_wif_readback import (
    build_readonly_gcloud_commands, inspect_readonly_cloud_wif,
)
from supplier_docs.pinned_wif_audit import (
    expected_pinned_provider_condition,
)

REPO = "fake-owner/private-supplier"
SHA = "a" * 40
CODE_SHA = "b" * 40
PROVIDER = ("projects/123456789012/locations/global/"
            "workloadIdentityPools/supplier-oidc-pool/providers/github-oidc")
SA = "supplier-docs-reader@fake-supplier-project.iam.gserviceaccount.com"
ID = "12345678901"
OWNER_ID = "98765432100"


def settings():
    return {
        "private_repo": True,
        "repository": REPO,
        "repository_id": ID,
        "owner_id": OWNER_ID,
        "branch_ref": "refs/heads/main",
        "workflow_ref": REPO + "/.github/workflows/supplier-readonly.yml@refs/heads/main",
        "event_name": "workflow_dispatch",
        "reader_service_account": SA,
        "provider_resource": PROVIDER,
        "provider_review_completed": True,
        "reader_share_scope_reviewed": True,
        "quota_and_billing_reviewed": True,
        "private_state_store_reviewed": True,
        "secret_json_keys_present": False,
        "live_access_enabled": False,
        "scheduled": False,
        "public_artifacts_enabled": False,
        "production_spapi_identity_reused": False,
    }


def github():
    return {
        "id": int(ID), "owner": {"id": int(OWNER_ID)},
        "full_name": REPO, "visibility": "private",
        "archived": False, "default_branch": "main",
        "default_branch_protected": False,
    }


def provider():
    return {
        "name": PROVIDER,
        "state": "ACTIVE", "disabled": False,
        "oidc": {"issuerUri": "https://token.actions.githubusercontent.com",
                 "allowedAudiences": []},
        "attributeMapping": {
            "google.subject": "assertion.sub",
            "attribute.repository_owner_id": "assertion.repository_owner_id",
            "attribute.repository_id": "assertion.repository_id",
            "attribute.ref": "assertion.ref",
            "attribute.event_name": "assertion.event_name",
            "attribute.workflow_ref": "assertion.workflow_ref",
            "attribute.workflow_sha": "assertion.workflow_sha",
            "attribute.sha": "assertion.sha",
            "attribute.repository_visibility": "assertion.repository_visibility",
            "attribute.runner_environment": "assertion.runner_environment",
        },
        "attributeCondition": expected_pinned_provider_condition(
            settings(), SHA, CODE_SHA),
    }


def policy():
    return {
        "bindings": [{
            "role": "roles/iam.workloadIdentityUser",
            "members": [
                "principalSet://iam.googleapis.com/projects/123456789012/"
                "locations/global/workloadIdentityPools/supplier-oidc-pool/"
                "attribute.repository_id/" + ID,
            ],
        }]
    }


class FakeGcloud:
    def __init__(self, *, data=None):
        self.calls = []
        self.data = data or [provider(), policy()]
        self.index = 0

    def __call__(self, argv):
        self.calls.append(argv)
        value = self.data[self.index]
        self.index += 1
        return SimpleNamespace(returncode=0, stdout=json.dumps(value),
                               stderr="FAKE_PRIVATE_GCLOUD_INFORMATION")


def inspect(fake=None, **kwargs):
    runner = FakeGcloud() if fake is None else fake
    config = {
        "settings": settings(),
        "github_repo_snapshot": github(),
        "reviewed_workflow_sha": SHA,
        "reviewed_source_commit_sha": CODE_SHA,
        "owner_approved_readonly": True,
        "executor": runner,
    }
    config.update(kwargs)
    return inspect_readonly_cloud_wif(**config)


class CloudReadbackTests(unittest.TestCase):
    def test_only_provider_describe_and_service_account_policy_reads(self):
        first, second = build_readonly_gcloud_commands(settings())
        self.assertEqual(first[:5],
                         ["gcloud", "iam", "workload-identity-pools",
                          "providers", "describe"])
        self.assertEqual(second[:4],
                         ["gcloud", "iam", "service-accounts", "get-iam-policy"])
        for cmd in (first, second):
            self.assertIn("--format=json", cmd)
            self.assertFalse(any(arg in cmd for arg in (
                "create", "update", "delete", "set-iam-policy",
                "add-iam-policy-binding", "keys", "impersonate-service-account")))
            self.assertEqual(cmd[0], "gcloud")

    def test_success_is_review_only_without_any_live_github_job(self):
        fake = FakeGcloud()
        report = inspect(fake)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(
            report["status"], "eligible_for_separate_manual_connection_review")
        self.assertFalse(report["actual_oidc_token_exchange_tested"])
        self.assertFalse(report["actual_sheets_access_tested"])
        self.assertFalse(report["google_iam_changed"])
        self.assertFalse(report["additional_cost_guaranteed_zero"])
        redacted = json.dumps(report)
        for sensitive in (REPO, PROVIDER, SA, ID, CODE_SHA):
            self.assertNotIn(sensitive, redacted)

    def test_no_approval_no_gcloud_calls(self):
        fake = FakeGcloud()
        with self.assertRaises(PermissionError):
            inspect(fake, owner_approved_readonly=False)
        self.assertEqual(fake.calls, [])

    def test_invalid_source_sha_is_refused_before_gcloud(self):
        fake = FakeGcloud()
        with self.assertRaises(ValueError):
            inspect(fake, reviewed_source_commit_sha="not-a-commit")
        self.assertEqual(fake.calls, [])

    def test_invalid_provider_or_spapi_identity_refused_before_gcloud(self):
        for modified in (
            {"provider_resource": "bad-provider"},
            {"reader_service_account":
                "amazon-spapi-worker@fake-project.iam.gserviceaccount.com"},
        ):
            fake = FakeGcloud()
            cfg = settings()
            cfg.update(modified)
            with self.subTest(modified=modified), self.assertRaises(ValueError):
                inspect(fake, settings=cfg)
            self.assertEqual(fake.calls, [])

    def test_provider_drift_blocks_observed_trust(self):
        wrong = provider()
        wrong["attributeCondition"] += " || true"
        fake = FakeGcloud(data=[wrong, policy()])
        result = inspect(fake)
        self.assertEqual(result["status"], "blocked_on_observed_trust_mismatch")

    def test_missing_policy_grant_is_blocked(self):
        result = inspect(FakeGcloud(data=[provider(), {"bindings": []}]))
        self.assertFalse(
            result["checks"]["dedicated_reader_iam_principalset_matches"])

    def test_gcloud_error_never_returns_private_provider_in_message(self):
        fake = FakeGcloud()
        def fail(argv):
            fake.calls.append(argv)
            return SimpleNamespace(
                returncode=1, stdout="", stderr="SECRET_ID_SENTINEL")
        with self.assertRaises(ValueError) as e:
            inspect(fail)
        self.assertNotIn("SECRET_ID_SENTINEL", str(e.exception))

    def test_timeout_fails_closed(self):
        def timeout(argv):
            raise subprocess.TimeoutExpired(argv, 20, stderr=b"PRIVATE_DATA")
        with self.assertRaises(ValueError) as e:
            inspect(timeout)
        self.assertNotIn("PRIVATE_DATA", str(e.exception))

    def test_invalid_json_and_oversize_rejected(self):
        for raw in ("oops", "[]", "{" + " " * 170_000 + "}"):
            def response(argv):
                return SimpleNamespace(returncode=0, stdout=raw, stderr="")
            with self.subTest(raw_size=len(raw)), self.assertRaises(ValueError):
                inspect(response)

    def test_github_repo_snapshot_must_be_explicit(self):
        runner = FakeGcloud()
        with self.assertRaises(ValueError):
            inspect(runner, github_repo_snapshot="fake")
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
