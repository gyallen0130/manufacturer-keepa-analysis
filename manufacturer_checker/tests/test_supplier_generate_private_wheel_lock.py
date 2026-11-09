"""Pure fake-wheel tests; never download a package or access real supplier data."""
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch
import hashlib
import io
import os
import tempfile
import unittest

from supplier_docs import generate_private_wheel_lock as generator


class SupplierPublicLockReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.input = Path(temp.name, "public.in")
        self.input.write_text(
            "google-api-python-client>=2,<3\n"
            "google-auth>=2,<3\n"
            "cryptography>=42,<47\n",
            encoding="utf-8",
        )
        self.env = {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "pull_request",
        }

    def _fake_pip(self, command, **kwargs):
        self.assertEqual(command[1:4], ["-m", "pip", "download"])
        self.assertIn("--only-binary=:all:", command)
        self.assertIn("--index-url", command)
        self.assertIn("https://pypi.org/simple", command)
        self.assertTrue(kwargs["capture_output"])
        self.assertEqual(kwargs["timeout"], 180)
        output = Path(command[command.index("--dest") + 1])
        names = [
            "google_api_python_client-2.1-py3-none-any.whl",
            "google_auth-2.2-py3-none-any.whl",
            "cryptography-45.0.0-cp311-abi3-manylinux_2_17_x86_64.whl",
        ]
        for name in names:
            (output / name).write_bytes(("fake-wheel-for-" + name).encode())
        return type("Result", (), {"returncode": 0})()

    def test_fake_wheels_are_content_hashed_and_sorted(self):
        out = io.StringIO()
        with patch.object(generator, "_INPUT", self.input), patch.dict(
            os.environ, self.env
        ), patch.object(generator.subprocess, "run", self._fake_pip), redirect_stdout(out):
            generator._run()
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0], "SUPPLIER_LOCK_BEGIN")
        self.assertEqual(lines[-1], "SUPPLIER_LOCK_END 3")
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(" --hash=sha256:" in row for row in lines[1:-1]))
        self.assertTrue(lines[1].startswith("SUPPLIER_LOCK_ROW cryptography=="))
        self.assertNotIn("fake-wheel-for", out.getvalue())

    def test_must_run_only_in_public_pr_ci(self):
        for changes in (
            {"GITHUB_ACTIONS": "false"},
            {"GITHUB_EVENT_NAME": "workflow_dispatch"},
            {"GITHUB_EVENT_NAME": "push"},
        ):
            env = {**self.env, **changes}
            called = []
            with patch.object(generator, "_INPUT", self.input), patch.dict(
                os.environ, env
            ), patch.object(generator.subprocess, "run",
                            lambda *args, **kwargs: called.append(True)):
                with self.assertRaises(ValueError):
                    generator._run()
            self.assertFalse(called)

    def test_changed_or_extra_dependencies_are_rejected(self):
        self.input.write_text(
            self.input.read_text() + "unreviewed-private-module>=0\n",
            encoding="utf-8",
        )
        called = []
        with patch.object(generator, "_INPUT", self.input), patch.dict(
            os.environ, self.env
        ), patch.object(generator.subprocess, "run",
                        lambda *args, **kwargs: called.append(True)):
            with self.assertRaises(ValueError):
                generator._run()
        self.assertFalse(called)

    def test_non_wheel_package_download_is_rejected(self):
        def fake(command, **kwargs):
            folder = Path(command[command.index("--dest") + 1])
            (folder / "untrusted_package-1.0.tar.gz").write_bytes(b"not a wheel")
            return type("Result", (), {"returncode": 0})()
        with patch.object(generator, "_INPUT", self.input), patch.dict(
            os.environ, self.env
        ), patch.object(generator.subprocess, "run", fake):
            with self.assertRaises(ValueError):
                generator._run()

    def test_network_failure_is_refused_without_lock_lines(self):
        def failure(*args, **kwargs):
            return type("Result", (), {"returncode": 1})()
        output = io.StringIO()
        with patch.object(generator, "_INPUT", self.input), patch.dict(
            os.environ, self.env
        ), patch.object(generator.subprocess, "run", failure), redirect_stdout(output):
            with self.assertRaises(ValueError):
                generator._run()
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
