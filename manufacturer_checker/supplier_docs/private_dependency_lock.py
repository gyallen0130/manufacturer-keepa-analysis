"""Strict offline syntax validator for the Linux Python 3.11 wheel hash snapshot.

Pip --require-hashes verifies downloaded bytes. This additional parser rejects
unexpected requirement syntax, unpinned versions, duplicated distributions,
unreviewed indexes and extra directives in a manually reviewed lock file.

It does not attest PyPI publisher identity or package code safety, prove
transitive completeness (pip install/pip check are required), or authorize a
private workflow to run.
"""
import re

_ROW = re.compile(
    r"^([a-z][a-z0-9-]*)==([0-9][a-zA-Z0-9.!+_-]*) --hash=sha256:([a-f0-9]{64})$"
)
_DIRECT = frozenset({
    "google-api-python-client", "google-auth", "cryptography"
})
_INDEX = "--index-url https://pypi.org/simple"
_BINARY = "--only-binary=:all:"


def inspect_hashed_private_requirements(contents):
    """Validate one reviewed wheel SHA per exact version; no URLs/overrides."""
    if not isinstance(contents, str) or not 1 <= len(contents) <= 20000:
        raise ValueError("a bounded reviewed dependency lock is required")
    lines = [
        line.strip() for line in contents.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if lines[:2] != [_BINARY, _INDEX]:
        raise ValueError("binary-only PyPI index options required")
    if len(lines) < 5 or len(lines) > 62:
        raise ValueError("unexpected number of locked wheel requirements")
    packages = {}
    for line in lines[2:]:
        match = _ROW.fullmatch(line)
        if not match:
            raise ValueError("unreviewed dependency syntax or non-hashed wheel")
        name, version, digest = match.groups()
        if name in packages:
            raise ValueError("duplicate dependency in reviewed wheel lock")
        packages[name] = (version, digest)
    if not _DIRECT.issubset(packages):
        raise ValueError("approved top-level Sheets and crypto dependencies missing")
    if list(packages) != sorted(packages):
        raise ValueError("wheel lock order must be stable for review")
    # Do not expose identifiers, package versions or hashes in public job
    # summaries unless explicitly intended for the public code review.
    return {
        "reviewed_wheel_count": len(packages),
        "direct_runtime_requirements_present": True,
        "exact_versions_and_sha256_present": True,
        "no_unreviewed_pip_options_present": True,
        "wheel_bytes_independently_verified_by_parser": False,
        "upstream_package_code_audited": False,
    }
