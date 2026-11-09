"""Synthetic text-only lock parser tests, plus exact public committed lock."""
from pathlib import Path
import unittest

from supplier_docs.private_dependency_lock import (
    inspect_hashed_private_requirements,
)


def real_public_lock():
    return (Path(__file__).resolve().parents[1] /
            "supplier_docs" / "approved-requirements-hashed.txt"
            ).read_text(encoding="utf-8")


class LockedPrivateRunnerTests(unittest.TestCase):
    def test_actual_pinned_requirements_have_sha_and_no_dynamic_index(self):
        result = inspect_hashed_private_requirements(real_public_lock())
        self.assertEqual(result["reviewed_wheel_count"], 22)
        self.assertTrue(result["direct_runtime_requirements_present"])
        self.assertFalse(result["upstream_package_code_audited"])
        self.assertFalse(result["wheel_bytes_independently_verified_by_parser"])

    def test_missing_hash_or_floating_version_rejected(self):
        lock = real_public_lock()
        for edit in (
            lock.replace(" --hash=sha256:", "", 1),
            lock.replace("==", ">=", 1),
            lock.replace(" --hash=sha256:", " --hash=md5:", 1),
        ):
            with self.subTest():
                with self.assertRaises(ValueError):
                    inspect_hashed_private_requirements(edit)

    def test_alternate_package_indexes_and_plaintext_urls_rejected(self):
        lock = real_public_lock()
        cases = (
            lock.replace("https://pypi.org/simple", "https://evil.example/simple"),
            lock + "\n--extra-index-url https://evil.example\n",
            lock + "\n-e git+https://evil.example/package\n",
            lock.replace("--only-binary=:all:", "--prefer-binary"),
        )
        for case in cases:
            with self.subTest(case=case[-60:]), self.assertRaises(ValueError):
                inspect_hashed_private_requirements(case)

    def test_duplicate_packages_and_order_changes_rejected(self):
        lock = real_public_lock()
        rows = [x for x in lock.splitlines() if "=="
                in x and not x.lstrip().startswith("#")]
        duplicated = lock + rows[0] + "\n"
        with self.assertRaises(ValueError):
            inspect_hashed_private_requirements(duplicated)
        shuffled = lock.replace(rows[0], "__FIRST__", 1).replace(
            rows[1], rows[0], 1).replace("__FIRST__", rows[1], 1)
        with self.assertRaises(ValueError):
            inspect_hashed_private_requirements(shuffled)

    def test_empty_or_oversized_lock_rejected(self):
        for invalid in ("", "x" * 20001, None):
            with self.subTest(kind=str(type(invalid))):
                with self.assertRaises(ValueError):
                    inspect_hashed_private_requirements(invalid)


if __name__ == "__main__":
    unittest.main()
