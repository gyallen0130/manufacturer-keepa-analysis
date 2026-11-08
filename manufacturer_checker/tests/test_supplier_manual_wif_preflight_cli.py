"""Offline-only tests of the explicit owner WIF read-only entrypoint."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from supplier_docs.manual_wif_preflight_cli import (
    _load_private_object, run_owner_preflight,
)

GOOD = "a" * 40


class ManualWifOwnerCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = self._write("settings.json", {"private_marker": "secret"})
        self.github = self._write("github.json", {"full_name": "fake/repo"})
        self.arguments = [
            "--settings-file", str(self.settings),
            "--github-snapshot-file", str(self.github),
            "--workflow-sha", GOOD, "--source-sha", GOOD,
        ]

    def _write(self, name, value):
        path = Path(self.temp.name) / name
        path.write_text(json.dumps(value), encoding="utf-8")
        os.chmod(path, 0o600)
        return path

    def _call(self, *, more=(), inspector=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        result = run_owner_preflight(
            self.arguments + list(more), inspector=inspector,
            output=stdout, errors=stderr)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_no_confirmation_rejects_before_call(self):
        seen = []
        status, out, err = self._call(
            inspector=lambda **kwargs: seen.append(kwargs))
        self.assertEqual(status, 2)
        self.assertFalse(seen)
        self.assertEqual(out, "")
        self.assertIn("confirm-readonly", err)

    def test_confirmed_gives_redacted_preflight_report(self):
        calls = []
        def fake_inspector(**kwargs):
            calls.append(kwargs)
            return {
                "status": "eligible_for_separate_manual_connection_review",
                "checks": {"google_oidc_provider_exactly_pinned": True},
            }
        status, out, err = self._call(
            more=["--confirm-readonly"], inspector=fake_inspector)
        self.assertEqual(status, 0)
        self.assertEqual(err, "")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["owner_approved_readonly"])
        self.assertFalse(json.loads(out)["actual_sheets_access_tested"])
        self.assertFalse(json.loads(out)["production_connection_authorized"])
        self.assertNotIn("secret", out)
        self.assertNotIn("fake/repo", out)

    def test_mismatch_remains_no_go_even_with_successful_gcloud_read(self):
        def mismatch(**_kwargs):
            return {"status": "blocked_on_observed_trust_mismatch",
                    "checks": {"google_oidc_provider_exactly_pinned": False}}
        status, out, err = self._call(
            more=["--confirm-readonly"], inspector=mismatch)
        self.assertEqual(status, 1)
        self.assertIn("blocked_on_observed_trust_mismatch", out)
        self.assertEqual(err, "")

    def test_private_input_parse_failure_hides_paths(self):
        self.settings.write_text('{"secret":', encoding="utf-8")
        os.chmod(self.settings, 0o600)
        status, out, err = self._call(more=["--confirm-readonly"])
        self.assertEqual(status, 1)
        self.assertEqual(out, "")
        self.assertNotIn(str(self.settings), err)
        self.assertNotIn("secret", err)

    def test_missing_private_file_hides_os_error(self):
        self.settings.unlink()
        status, out, err = self._call(more=["--confirm-readonly"])
        self.assertEqual(status, 1)
        self.assertEqual(out, "")
        self.assertNotIn(str(self.settings), err)

    def test_private_file_permissions_are_checked_on_posix(self):
        if os.name != "posix":
            self.skipTest("POSIX file permissions")
        os.chmod(self.settings, 0o644)
        with self.assertRaises(ValueError):
            _load_private_object(str(self.settings))

    def test_symlink_input_rejected(self):
        link = Path(self.temp.name) / "linked.json"
        try:
            link.symlink_to(self.settings)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaises(ValueError):
            _load_private_object(str(link))

    def test_absolute_path_required(self):
        with self.assertRaises(ValueError):
            _load_private_object("settings.json")

    def test_non_object_input_rejected(self):
        self.settings.write_text("[]", encoding="utf-8")
        os.chmod(self.settings, 0o600)
        with self.assertRaises(ValueError):
            _load_private_object(str(self.settings))


if __name__ == "__main__":
    unittest.main()
