"""Review-only hash lock generator for PUBLIC Python wheel dependencies.

Only allowed in public synthetic-only CI. Downloads PyPI wheels, computes their
actual SHA256 bytes, and prints lock lines for manual review. This DOES NOT
commit a lock, install packages, inspect supplier records, load credentials,
or imply that an upstream package has been audited.

The approved lock must be committed separately and verified independently
before a private live workflow is allowed to use it.
"""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

_ROOT = Path(__file__).resolve().parent
_INPUT = _ROOT / "private_runner_deps.in"
_REQUIRED = frozenset({
    "google-api-python-client", "google-auth", "cryptography"
})
_WHEEL = re.compile(
    r"^([A-Za-z0-9_]+)-([A-Za-z0-9_.!+]+)-.+\.whl$", re.ASCII
)


def _distribution(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _run():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("public CI wheel resolution only")
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        raise ValueError("must run only on a synthetic PR CI job")
    expected_input = {
        "google-api-python-client>=2,<3",
        "google-auth>=2,<3",
        "cryptography>=42,<47",
    }
    actual = {x.strip() for x in _INPUT.read_text(
        encoding="utf-8").splitlines() if x.strip() and not x.lstrip().startswith("#")}
    if actual != expected_input:
        raise ValueError("dependency inputs changed; manual review required")
    with tempfile.TemporaryDirectory() as folder:
        cmd = [
            sys.executable, "-m", "pip", "download", "--only-binary=:all:",
            "--no-cache-dir", "--disable-pip-version-check",
            "--index-url", "https://pypi.org/simple",
            "-r", str(_INPUT), "--dest", folder,
        ]
        # Never print pip output: it can contain unsafe index/proxy metadata.
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise ValueError("PyPI binary dependency resolution failed")
        found = {}
        for wheel in sorted(Path(folder).iterdir()):
            match = _WHEEL.fullmatch(wheel.name)
            if not match or not wheel.is_file():
                raise ValueError("non-wheel/unexpected dependency download")
            name, version = match.groups()
            dist = _distribution(name)
            if dist in found:
                raise ValueError("duplicate resolved distribution")
            digest = hashlib.file_digest(wheel.open("rb"), "sha256").hexdigest()
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("invalid resolved wheel digest")
            found[dist] = f"{dist}=={version} --hash=sha256:{digest}"
        if not _REQUIRED.issubset(found) or not 3 <= len(found) <= 60:
            raise ValueError("missing required wheel or unexpectedly broad dependency set")
        print("SUPPLIER_LOCK_BEGIN")
        for name in sorted(found):
            print("SUPPLIER_LOCK_ROW " + found[name])
        print("SUPPLIER_LOCK_END " + str(len(found)))


if __name__ == "__main__":
    try:
        _run()
    except Exception:
        sys.stderr.write("Supplier public-wheel hash review failed (details suppressed).\n")
        raise SystemExit(1)
