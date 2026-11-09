"""One-call, private supplier lookup workflow using an EXTERNALLY authorized reader.

The application (ChatGPT/Drive connector, later an authorized service) must
authenticate the current user, independently verify source access and visible
tab metadata, and construct approved_tab_metadata before invoking this code.

A synchronous injected fetch_formula_range callback performs each preplanned
read. The module NEVER acquires Google credentials, performs networking on its
own, stores rows, logs identifiers, writes to Drive/GitHub or authorizes sales.

IMPORTANT: the callback and approved metadata are TRUSTED INPUTS supplied by
the application's authenticated boundary. Boolean assertions are NOT access
controls; do not offer this function to arbitrary web/API clients.
"""
from .multi_source_readonly import validate_source_lookup
from .private_hit_review import validate_private_reviewer_context
from .supplier_query_planner import (
    plan_supplier_sheet_reads, build_private_page_manifest,
    summarize_plan_without_private_sources,
)
from .connector_sheets_paged import (
    inspect_selected_connector_sheet_pages,
    inspect_selected_connector_sheet_pages_for_review,
)

SCHEMA_VERSION = "private-supplier-lookup-session-v1"
_ALLOWED_REPLY = frozenset((
    "spreadsheet_id", "sheet_name", "requested_range",
    "value_render_option", "rows",
))


def _check_search(search):
    if not isinstance(search, dict) or set(search) != {"field", "query"}:
        raise ValueError("a single exact bounded search is required")
    validate_source_lookup(search["field"], search["query"])


def run_supplier_lookup_once(
        *, supplier_query, search, approved_tab_metadata, fetch_formula_range,
        include_private_hits=False, reviewer_context=None, max_hits=20):
    """Plan, fetch, bind, parse and search a bounded approved supplier selection.

    fetch_formula_range must accept keyword args:
      spreadsheet_id, sheet_name, requested_range, value_render_option='FORMULA'
    and return a dict with those four echoed identifiers and 'rows'.

    The callback must be an authenticated, read-only application adapter.
    It MUST raise on access/timeout/API failure. An empty successful response
    is allowed, but a failed read may NEVER be replaced by empty rows.

    The regular response is anonymous and safe to display as aggregate.
    include_private_hits=True returns PRIVATE product names and source URLs:
    only to the same independently authenticated user's private session.
    No secret source IDs, supplier names or row contents in public fields.
    """
    _check_search(search)
    if type(include_private_hits) is not bool:
        raise ValueError("private view selector must be bool")
    if include_private_hits:
        # Fail BEFORE any connector API activity or private data handling.
        validate_private_reviewer_context(reviewer_context)
    elif reviewer_context is not None:
        raise ValueError("private confirmation only valid with explicit review")
    if not callable(fetch_formula_range):
        raise ValueError("authenticated read callback required")

    plan = plan_supplier_sheet_reads(
        supplier_query=supplier_query, approved_tab_metadata=approved_tab_metadata)
    coverage = summarize_plan_without_private_sources(plan)
    responses = []
    for source in plan["selected_sources"]:
        requests = [source["header_range"]] + [
            p["requested_range"] for p in source["data_pages"]]
        for rng in requests:
            args = {
                "spreadsheet_id": source["spreadsheet_id"],
                "sheet_name": source["sheet_name"],
                "requested_range": rng,
                "value_render_option": "FORMULA",
            }
            try:
                raw = fetch_formula_range(**args)
            except Exception:
                # The connector exception might contain a source ID, JAN,
                # a signed URL or OAuth token. Never echo/chain/log it.
                raise RuntimeError("authorized connector range read failed") from None
            if not isinstance(raw, dict) or set(raw) != _ALLOWED_REPLY:
                raise ValueError("connector returned invalid range envelope")
            if any(raw[key] != args[key] for key in args):
                raise ValueError("connector range binding or FORMULA mode mismatch")
            # Do not allow the caller to skip a page or label a failed fetch
            # as success; actual transport/authorization is the host's duty.
            responses.append({
                "spreadsheet_id": raw["spreadsheet_id"],
                "sheet_name": raw["sheet_name"],
                "requested_range": raw["requested_range"],
                "rows": raw["rows"],
            })

    manifest = build_private_page_manifest(
        plan=plan, connector_responses=responses)
    public_result = inspect_selected_connector_sheet_pages(
        manifest=manifest, search=search)
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "selected_supplier_lookup_completed",
        "public_summary": public_result["public_summary"],
        "public_search_summary": public_result["public_search_summary"],
        "coverage": coverage,
        "private_details_returned": False,
        "python_google_auth_verified": False,
        "external_authentication_required": True,
        "source_writes": 0,
    }
    if include_private_hits:
        # A URL-only gid map cannot safely distinguish multiple tabs in the
        # SAME spreadsheet. Do not make guessed deep links in that case.
        counts = {}
        for source in plan["selected_sources"]:
            url = "https://docs.google.com/spreadsheets/d/" + source["spreadsheet_id"] + "/edit"
            counts[url] = counts.get(url, 0) + 1
        gid_map = {
            "https://docs.google.com/spreadsheets/d/" + src["spreadsheet_id"] + "/edit":
                src["sheet_gid"]
            for src in plan["selected_sources"]
            if counts["https://docs.google.com/spreadsheets/d/" + src["spreadsheet_id"] + "/edit"] == 1
        }
        private = inspect_selected_connector_sheet_pages_for_review(
            manifest=manifest,
            search=search,
            reviewer_context=reviewer_context,
            source_labels=[s["supplier_label"] for s in plan["selected_sources"]],
            sheet_gid_by_url=gid_map,
            max_hits=max_hits,
        )
        result["private_details_returned"] = True
        result["private_review"] = private

    return result
