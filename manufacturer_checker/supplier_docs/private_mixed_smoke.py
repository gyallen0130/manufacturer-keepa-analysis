"""Private, manual smoke-test gateway for bounded Excel + Sheets searches.

The default action is offline-only. Live Sheets reading is opt-in and requires
an existing, independently approved read-only credential. This module never
creates credentials, modifies IAM, schedules work or persists source rows.
Only explicitly public aggregate dictionaries are returned or printed.
"""
import argparse
import json
from pathlib import Path
import sys

from .authorized_mixed_probe import inspect_authorized_mixed_sources
from .local_excel_bridge import inspect_selected_local_excel, validate_excel_manifest
from .multi_source_readonly import MAX_SOURCES, validate_source_lookup
from .sheets_multi_bridge import validate_multi_sheet_manifest

MAX_MANIFEST_BYTES = 64 * 1024


def _read_manifest(folder, filename, *, optional=False):
    path = folder / filename
    if optional and not path.exists():
        return None
    if (path.is_symlink() or not path.is_file()
            or not 0 < path.stat().st_size <= MAX_MANIFEST_BYTES):
        raise ValueError("invalid approved private input")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def run_private_mixed_smoke(*, private_dir, execute_readonly=False,
                            service_factory=None):
    """Perform local preflight, optionally execute a preapproved Sheets read.

    The private directory holds approved_excel.json, approved_sheets.json and
    optional approved_search.json, as well as explicitly selected Excel files.
    Return values are deliberately restricted to anonymous public summaries.
    Do not print exception details: provider errors may include file IDs.
    """
    root = Path(private_dir)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("private input directory is unavailable")
    excel = _read_manifest(root, "approved_excel.json")
    sheets = _read_manifest(root, "approved_sheets.json")
    lookup = _read_manifest(root, "approved_search.json", optional=True)

    selected_excel = validate_excel_manifest(excel)
    selected_sheets = validate_multi_sheet_manifest(sheets)
    if len(selected_excel) + len(selected_sheets) > MAX_SOURCES:
        raise ValueError("combined source tab limit exceeded")
    if lookup is not None:
        if not isinstance(lookup, dict) or set(lookup) != {"field", "query"}:
            raise ValueError("invalid approved search")
        validate_source_lookup(lookup["field"], lookup["query"])

    # Explicitly inspect local Excel before building or calling a Google client.
    local = inspect_selected_local_excel(root_dir=root, manifest=excel)
    if not execute_readonly:
        return {
            "status": "offline_preflight_only",
            "excel_tabs_checked": len(selected_excel),
            "sheets_tabs_not_yet_read": len(selected_sheets),
            "local_record_candidates": local["public_summary"]["record_count"],
            "google_api_calls": 0,
            "source_writes": 0,
            "real_google_auth_verified": False,
            "profit_calculation_allowed": False,
        }

    # The caller explicitly owns this boundary and must independently verify
    # that the factory uses the intended approved Reader, not a wider identity.
    if not callable(service_factory):
        raise ValueError("explicit approved read-only factory required")
    merged = inspect_authorized_mixed_sources(
        root_dir=root, excel_manifest=excel, sheets_manifest=sheets,
        service_factory=service_factory, search=lookup,
    )
    return {
        "status": "readonly_service_probe_completed",
        "public_summary": merged["public_summary"],
        "public_search_summary": merged.get("public_search_summary"),
        "real_google_auth_verified": False,  # Caller must audit identity.
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Offline-only safety preflight for approved Excel/Sheets"
    )
    parser.add_argument("--private-dir", required=True)
    args = parser.parse_args(argv)
    try:
        result = run_private_mixed_smoke(private_dir=args.private_dir)
    except Exception:
        # Never echo a third-party API exception, local path or private query.
        print("Preflight failed; inspect private inputs locally.", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
