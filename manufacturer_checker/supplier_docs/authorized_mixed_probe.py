"""Private one-shot mixed supplier probe with injected read-only Sheets service.

No credentials are obtained in this module. The caller passes an already-
authorized, read-only Sheets v4 service factory; this does NOT reuse ChatGPT
connector OAuth tokens. Real Excel stays on the operator's private machine.
All results except aggregate public_summary / public_search_summary are
PRIVATE and must never be logged or uploaded to public GitHub/CI.
"""
from .local_excel_bridge import (
    inspect_selected_local_excel, validate_excel_manifest,
)
from .sheets_multi_bridge import (
    inspect_selected_google_sheets, validate_multi_sheet_manifest,
)
from .multi_source_readonly import MAX_SOURCES, validate_source_lookup
from .mixed_source_readonly import combine_selected_source_results


def inspect_authorized_mixed_sources(*, root_dir, excel_manifest,
                                     sheets_manifest, service_factory,
                                     search=None):
    """Validate both manifests before invoking any service factory/API calls.

    The data read remains bounded to five explicit tabs across both formats.
    On invalid Excel or search, no Google API access is attempted. No
    scheduling, Drive discovery, source mutation or profit decisions.
    """
    if not callable(service_factory):
        raise ValueError('a preapproved read-only Sheets service factory is required')
    selected_excel = validate_excel_manifest(excel_manifest)
    selected_sheets = validate_multi_sheet_manifest(sheets_manifest)
    if len(selected_excel) + len(selected_sheets) > MAX_SOURCES:
        raise ValueError('only five combined source tabs are authorized')
    if search is not None:
        if not isinstance(search, dict) or set(search) != {'field', 'query'}:
            raise ValueError('invalid private combined lookup')
        validate_source_lookup(search['field'], search['query'])

    # Local Excel validation and read comes FIRST, to avoid requesting any
    # remote Sheets data if the local path / tab is inaccessible or unsafe.
    excel_private = inspect_selected_local_excel(
        root_dir=root_dir, manifest=excel_manifest)
    # The credentials are provided by the operator, and should be scoped to
    # https://www.googleapis.com/auth/spreadsheets.readonly outside this module.
    service = service_factory()
    if service is None:
        raise ValueError('authorized Sheets service was not available')
    sheets_private = inspect_selected_google_sheets(
        service, manifest=sheets_manifest)
    return combine_selected_source_results(
        [excel_private, sheets_private], search=search)
