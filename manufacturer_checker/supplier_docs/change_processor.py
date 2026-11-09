"""Read-only handoff from approved Drive deltas to bounded Sheets summaries.

The only network operations allowed here belong to the injected Sheets v4
read-only client. No Drive browsing, file downloads, state writes, Keepa,
Amazon API calls or automatic acknowledgments happen in this module.

Approved mappings, source IDs, and the private review list are sensitive.
Only the returned summary is suitable for routine status reporting.
"""
from collections import Counter
import re

from .parser import DOCUMENT_TYPES
from .snapshot_store import review_queue
from .readers import sheets_selected_tabs_summary

SHEETS_MIME = 'application/vnd.google-apps.spreadsheet'
MAX_FILES = 10
MAX_TABS_PER_FILE = 10
MAX_CELLS = 50000


def _column_count(end_col):
    if not isinstance(end_col, str) or not re.fullmatch(r'[A-Z]{1,2}', end_col):
        raise ValueError('invalid bounded column')
    width = 0
    for char in end_col:
        width = width * 26 + ord(char) - ord('A') + 1
    if width > 26:
        raise ValueError('column budget exceeds Z')
    return width


def inspect_approved_sheet_changes(
        sheets_service, *, previous, current, approved_targets,
        rows_per_tab=40, end_col='L', max_files=MAX_FILES,
        max_total_cells=MAX_CELLS):
    """Inspect only changed, explicitly approved Google Sheet tabs.

    approved_targets is a private mapping:
      {(folder_id, file_id): {exact_tab_title: explicit_document_type}}

    All selection and aggregate cell budget checks happen BEFORE an API call.
    Unselected Sheets and binary files remain pending. Even a successful
    parsed result is NOT a completion receipt: humans or a later validated
    workflow must explicitly acknowledge processing before a baseline advance.
    """
    if previous is None:
        raise ValueError('initial inventory baseline must be approved first')
    if (type(max_files) is not int or not 1 <= max_files <= MAX_FILES
            or type(rows_per_tab) is not int or not 2 <= rows_per_tab <= 1000
            or type(max_total_cells) is not int or not 1 <= max_total_cells <= MAX_CELLS
            or not isinstance(approved_targets, dict)):
        raise ValueError('invalid processing limits or approved manifest')

    width = _column_count(end_col)
    queue = review_queue(previous, current)
    entries = queue['private_queue']
    candidate_map = {
        (item['folder_id'], item['file_id']): item for item in entries
    }
    if len(approved_targets) > max_files:
        raise ValueError('too many approved files')

    total_cells = 0
    for location, tabs in approved_targets.items():
        if (not isinstance(location, tuple) or len(location) != 2
                or any(not isinstance(v, str) for v in location)
                or location not in candidate_map
                or candidate_map[location]['mime_type'] != SHEETS_MIME
                or not isinstance(tabs, dict)
                or not 1 <= len(tabs) <= MAX_TABS_PER_FILE):
            raise ValueError('unapproved, unchanged or unsupported file')
        for title, doc_type in tabs.items():
            if (not isinstance(title, str) or not title.strip()
                    or '!' in title or doc_type not in DOCUMENT_TYPES):
                raise ValueError('invalid approved sheet tab')
        total_cells += len(tabs) * rows_per_tab * width
        if total_cells > max_total_cells:
            raise ValueError('aggregate read budget exceeded')

    private_results = []
    aggregate_risks = Counter()
    aggregate_warnings = Counter()
    total_records = 0
    # Iterate deterministic, explicitly approved inputs only.
    for location, tabs in approved_targets.items():
        _, file_id = location
        parsed = sheets_selected_tabs_summary(
            sheets_service, spreadsheet_id=file_id,
            tab_document_types=tabs, max_rows_per_tab=rows_per_tab,
            end_col=end_col, max_tabs=MAX_TABS_PER_FILE)
        aggregate_risks.update(parsed['risk_counts'])
        aggregate_warnings.update(parsed['warning_code_counts'])
        total_records += parsed['total_record_count']
        private_results.append({
            'location': location,
            'status': 'inspection_requires_review',
            'tab_summaries': parsed['tabs'],
            'risk_counts': parsed['risk_counts'],
            'warning_code_counts': parsed['warning_code_counts'],
        })

    # These still require a separate review / supported acquisition path.
    pending = [loc for loc in candidate_map if loc not in approved_targets]
    return {
        'summary': {
            'candidate_files': len(entries),
            'inspected_sheets': len(private_results),
            'pending_files': len(pending),
            'unavailable_needs_review': queue['summary']['unavailable_needs_review'],
            'candidate_rows': total_records,
            'risk_counts': dict(sorted(aggregate_risks.items())),
            'warning_code_counts': dict(sorted(aggregate_warnings.items())),
            'requires_explicit_acknowledgement': True,
        },
        'private_inspections': private_results,
        'pending_locations': pending,
        'unavailable_locations': queue['unavailable_locations'],
        'baseline_advanced': False,
    }
