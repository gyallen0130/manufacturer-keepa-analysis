"""Manual-only offline Excel probe.

Run from an authorized private environment. It prints anonymous aggregate
counts only, even for invalid inputs. It does not connect to any service,
persist normalized product rows, execute macros, modify source Excel, or
accept remote URLs. Keep private manifest and lookup values out of CI logs.
"""
import argparse
import json
from pathlib import Path
import sys

from .local_excel_bridge import inspect_selected_local_excel

MAX_MANIFEST_BYTES = 32768


def _load_private_json(path_string):
    path = Path(path_string)
    if (not path.is_file() or path.is_symlink()
            or path.stat().st_size > MAX_MANIFEST_BYTES
            or path.suffix.lower() != '.json'):
        raise ValueError('invalid private JSON input')
    return json.loads(path.read_text(encoding='utf-8'))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Private, read-only 1-5 Excel-sheet aggregation; no product output')
    parser.add_argument('--root', required=True, help='authorized local Excel directory')
    parser.add_argument('--manifest', required=True, help='private approved JSON file')
    parser.add_argument('--search-manifest', help='optional private JSON with field/query')
    args = parser.parse_args(argv)
    try:
        manifest = _load_private_json(args.manifest)
        search = (_load_private_json(args.search_manifest)
                  if args.search_manifest else None)
        result = inspect_selected_local_excel(
            root_dir=args.root, manifest=manifest, search=search)
        public = {'summary': result['public_summary']}
        if search is not None:
            public['search_summary'] = result['public_search_summary']
        # Both summaries are deliberate small, identifier-free projections.
        print(json.dumps(public, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, TypeError, KeyError, OSError, json.JSONDecodeError):
        # Raw exception text can reveal source filenames/values; do not echo.
        print('Private Excel probe rejected invalid or unrecognized input',
              file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
