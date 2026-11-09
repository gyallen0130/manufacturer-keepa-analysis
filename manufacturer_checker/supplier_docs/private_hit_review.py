"""Explicitly opted-in, in-memory PRIVATE supplier hit details.

This is NOT an authentication system. The caller must already have checked
Google Drive/file access and the authenticated session's private destination.
The returned value is PRIVATE: never print, log, persist, email, send to public
CI, write to GitHub or present to other users. Unlike anonymous summaries,
this function intentionally includes product names, identifiers and origins.

No Google credentials, network, filesystem access, source writes, Keepa,
SP-API, profit calculations or purchase actions occur here.
"""
import re

from .multi_source_readonly import search_selected_sources, validate_source_lookup

MAX_REVIEW_HITS = 20
_REVIEW_CONTEXT = {
    'source_access_checked': True,
    'private_recipient_checked': True,
    'private_display_requested': True,
    'no_public_logging': True,
}
_WARNING_CODE = re.compile(r'^[A-Z][A-Z0-9_]{0,79}$')


def _safe_text(value, limit=500):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ValueError('invalid private normalized text')
    if len(value) > limit:
        raise ValueError('private display field exceeds bound')
    return value


def validate_private_reviewer_context(context):
    # The flags document checks made by the trusted application layer.
    # A caller setting True does not constitute identity/access proof.
    if not isinstance(context, dict) or context != _REVIEW_CONTEXT:
        raise ValueError('private review not authorized by application boundary')


def prepare_selected_private_hit_review(*, combined, search, reviewer_context,
                                        source_labels=None, max_hits=MAX_REVIEW_HITS,
                                        sheet_gid_by_url=None):
    """Prepare bounded selected-source hits for an authenticated private view.

    Source labels are declared by the caller after independently checking
    file names and supplier identity. They are never inferred or confirmed
    by this function. With no labels, the file path/Sheet tab is shown instead.

    Return is PRIVATE ONLY and must never be serialized to a shared log.
    The regular public-only one-shot API remains unchanged.
    """
    validate_private_reviewer_context(reviewer_context)
    if (not isinstance(search, dict) or set(search) != {'field', 'query'}):
        raise ValueError('private review requires a bounded lookup')
    field, _ = validate_source_lookup(search['field'], search['query'])
    if type(max_hits) is not int or not 1 <= max_hits <= MAX_REVIEW_HITS:
        raise ValueError('invalid private review limit')
    if not isinstance(combined, dict):
        raise ValueError('private normalized search result required')
    docs = combined.get('private_normalized_docs')
    kinds = combined.get('private_source_kinds')
    origins = combined.get('private_source_origins')
    hits = combined.get('private_hits')
    public = combined.get('public_search_summary')
    if (not isinstance(docs, list) or not 1 <= len(docs) <= 5
            or not isinstance(kinds, list) or len(kinds) != len(docs)
            or not isinstance(origins, list) or len(origins) != len(docs)
            or not isinstance(hits, list) or not isinstance(public, dict)
            or type(public.get('hits_returned')) is not int
            or not 0 <= len(hits) <= 100
            or len(hits) != public['hits_returned']):
        raise ValueError('private review source or search metadata invalid')

    if source_labels is None:
        source_labels = [None] * len(docs)
    if (not isinstance(source_labels, (list, tuple))
            or len(source_labels) != len(docs)):
        raise ValueError('private source labels must match selected source tabs')
    for label in source_labels:
        if (label is not None and
                (not isinstance(label, str) or not label.strip()
                 or len(label) > 120 or any(ord(c) < 32 for c in label))):
            raise ValueError('private source label invalid')

    # Recompute in memory to detect a forged/stale hit pointer or different
    # lookup, before presenting any sensitive product values.
    verified = search_selected_sources(
        {'private_normalized_docs': docs}, **search)
    if (hits != verified['private_hits']
            or public != verified['public_summary']):
        raise ValueError('private lookup evidence inconsistent')

    # Validate all selected source provenance before revealing first hit.
    for idx, (doc, kind, origin) in enumerate(zip(docs, kinds, origins)):
        if (not isinstance(doc, dict) or not isinstance(origin, dict)
                or kind not in ('excel', 'sheets')
                or origin.get('source_kind') != kind
                or origin.get('source_sheet') != doc.get('source_sheet')
                or doc.get('source_status') not in (
                    'parsed', 'mapped_review', 'labeled_review',
                    'needs_review', 'empty')):
            raise ValueError('private origin binding invalid')
        if kind == 'excel':
            if (set(origin) != {'source_kind', 'relative_path', 'source_sheet'}
                    or not isinstance(origin['relative_path'], str)
                    or not 1 <= len(origin['relative_path']) <= 300):
                raise ValueError('private Excel origin invalid')
        else:
            if (set(origin) != {'source_kind', 'source_url', 'source_sheet'}
                    or origin.get('source_url') != doc.get('source_url')
                    or not isinstance(origin.get('source_url'), str)
                    or not origin['source_url'].startswith(
                        'https://docs.google.com/spreadsheets/d/')):
                raise ValueError('private Google Sheets origin invalid')

    # The caller must independently verify each gid from Google Sheets
    # metadata in its authenticated session. This function cannot prove it.
    if sheet_gid_by_url is None:
        sheet_gid_by_url = {}
    if (not isinstance(sheet_gid_by_url, dict)
            or len(sheet_gid_by_url) > len(docs)):
        raise ValueError('invalid authenticated sheet location mapping')
    allowed_urls = {
        origin['source_url'] for kind, origin in zip(kinds, origins)
        if kind == 'sheets'
    }
    for source_url, gid in sheet_gid_by_url.items():
        if (not isinstance(source_url, str)
                or source_url not in allowed_urls
                or type(gid) is not int
                or not 0 <= gid <= 2147483647):
            raise ValueError('invalid or unselected Sheets gid mapping')

    selected = []
    for hit in hits[:max_hits]:
        si, ri = hit['source_index'], hit['record_index']
        doc, origin, kind = docs[si], origins[si], kinds[si]
        record = doc['records'][ri]
        if (hit.get('match_field') != field
                or record['source_row'] != hit['source_row']
                or record.get('source_file_id') != doc.get('source_file_id')
                or record.get('source_sheet') != doc.get('source_sheet')):
            raise ValueError('private hit source pointer mismatch')

        warning_codes = []
        for warning in doc.get('warnings', []):
            if warning.get('row') == record['source_row']:
                warning_codes.extend(warning.get('codes', []))
        if any(not isinstance(c, str) or not _WARNING_CODE.fullmatch(c)
               for c in warning_codes):
            raise ValueError('invalid private warning evidence')
        warning_codes = sorted(set(warning_codes))
        risks = record.get('risk_codes', [])
        if (not isinstance(risks, list)
                or any(not isinstance(c, str) or not _WARNING_CODE.fullmatch(c)
                       for c in risks)):
            raise ValueError('invalid private risk evidence')

        candidates = record.get('asin_candidates', [])
        if (not isinstance(candidates, list) or len(candidates) > 20
                or any(not isinstance(v, str) or
                       not re.fullmatch(r'[A-Z0-9]{10}', v)
                       for v in candidates)):
            raise ValueError('invalid private ASIN candidates')

        label = source_labels[si]
        if label is None:
            label = (origin['relative_path'] if kind == 'excel'
                     else doc['source_sheet'])
        row_url = None
        if kind == 'sheets' and origin['source_url'] in sheet_gid_by_url:
            # Exact selected tab/range, no guessed gid, no API call.
            gid = sheet_gid_by_url[origin['source_url']]
            line = record['source_row']
            row_url = f"{origin['source_url']}#gid={gid}&range=A{line}:O{line}"
        selected.append({
            'supplier_or_source_label': label,
            'label_provenance': ('caller_declared_unverified'
                                 if source_labels[si] is not None
                                 else 'source_file_or_tab'),
            'source_kind': kind,
            'original_file_path': (origin['relative_path']
                                   if kind == 'excel' else None),
            'original_sheet_url': (origin['source_url']
                                   if kind == 'sheets' else None),
            'original_sheet_tab': _safe_text(doc['source_sheet'], 128),
            'original_physical_row': record['source_row'],
            'original_row_url': row_url,
            'row_link_gid_verified_by_this_function': False,
            'matched_field': field,
            'manufacturer_name': _safe_text(
                record.get('manufacturer_name_raw')),
            'product_name': _safe_text(record.get('product_name_raw')),
            'model_number': _safe_text(record.get('model_number')),
            'jan_candidate': _safe_text(record.get('jan_string'), 14),
            'asin_candidates': list(candidates),
            'warning_codes': warning_codes,
            'risk_codes': sorted(set(risks)),
            'candidate_only': True,
            'identifier_or_selling_unit_confirmed': False,
            'cost_or_price_disclosed': False,
            'purchase_allowed': False,
        })

    return {
        'schema_version': 'private-selected-hit-review-v1',
        'privacy_classification': 'PRIVATE_USER_ONLY_NEVER_LOG',
        'source_access_verified_by_this_function': False,
        'user_identity_verified_by_this_function': False,
        'explicit_private_view_requested': True,
        'selected_source_tabs': len(docs),
        'selected_source_only': True,
        'all_supplier_folders_searched': False,
        'matched_hits_total': len(hits),
        'hits_displayed': len(selected),
        'hits_truncated_for_review': len(hits) > len(selected)
                                      or bool(public.get('results_truncated')),
        'price_disclosure_allowed': False,
        'profit_calculation_allowed': False,
        'purchase_allowed': False,
        'source_writes': 0,
        'private_hits': selected,
    }
