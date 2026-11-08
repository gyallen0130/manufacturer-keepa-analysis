"""Read-only, bounded multi-supplier normalization and local search.

Callers supply pre-authorized, already-fetched rows. This module makes NO
Google Drive, GitHub, Keepa, SP-API or Amazon calls, creates no files, does
not infer missing purchase prices, and never authorizes profit or orders.

PRIVATE: normalized_docs and private_hits (contain source references and
product identifiers). LOG-SAFE: public_summary (counts only).
"""
import re
import unicodedata

from .parser import DOCUMENT_TYPES, parse_rows

MAX_SOURCES = 5
MAX_ROWS_PER_SOURCE = 200
MAX_COLS_PER_ROW = 40
MAX_SEARCH_HITS = 100
LOOKUP_FIELDS = frozenset((
    'jan_string', 'asin_candidate', 'product_name_raw',
    'model_number', 'manufacturer_name_raw',
))
LOOKUP_ALIASES = {
    'jan': 'jan_string', 'asin': 'asin_candidate',
    'product': 'product_name_raw', 'model': 'model_number',
    'manufacturer': 'manufacturer_name_raw',
}
_ID = re.compile(r'^[A-Za-z0-9_-]{10,256}$')
_ASIN = re.compile(r'^[A-Z0-9]{10}$')
_JAN = re.compile(r'^[0-9]{8,14}$')


def _text(value):
    return unicodedata.normalize('NFKC', str(value or '')).strip().casefold()


def _check_specs(specs):
    if (not isinstance(specs, (list, tuple))
            or not 1 <= len(specs) <= MAX_SOURCES
            or not all(isinstance(s, dict) for s in specs)):
        raise ValueError('select between 1 and 5 authorized suppliers')
    seen = set()
    for s in specs:
        doc_type = s.get('document_type')
        rows = s.get('rows')
        file_id = s.get('source_file_id')
        sheet = s.get('source_sheet')
        header = s.get('header_row')
        if (doc_type not in DOCUMENT_TYPES
                or not isinstance(file_id, str) or not _ID.fullmatch(file_id)
                or not isinstance(sheet, str) or not 1 <= len(sheet) <= 128
                or not isinstance(rows, (list, tuple))
                or not 1 <= len(rows) <= MAX_ROWS_PER_SOURCE
                or any(not isinstance(row, (list, tuple))
                       or len(row) > MAX_COLS_PER_ROW for row in rows)
                or (header is not None and
                    (type(header) is not int or not 1 <= header <= len(rows)))):
            raise ValueError('invalid or oversized selected source')
        source_key = (file_id, sheet)
        if source_key in seen:
            raise ValueError('duplicate source selected')
        seen.add(source_key)
        url = s.get('source_url', '')
        if not isinstance(url, str) or len(url) > 2000:
            raise ValueError('invalid original source URL')


def normalize_selected_sources(specs):
    """Normalize 1-5 explicitly selected private worksheet windows.

    Source metadata and every normalized row are PRIVATE even when
    include_sensitive=False: JAN, ASIN, source IDs and product names are
    not suitable for public GitHub or CI logs. Source-level summaries only
    report number of records, mapped fields and warnings.
    """
    _check_specs(specs)
    normalized = []
    mapped_coverage = {}
    ambiguous_field_source_counts = {}
    totals = {'records': 0, 'warnings': 0, 'rows_scanned': 0,
              'with_jan': 0, 'with_asin': 0, 'with_model': 0,
              'cost_present': 0, 'cost_tax_unknown': 0}
    for spec in specs:
        rows = spec['rows']
        result = parse_rows(
            rows, document_type=spec['document_type'],
            source_file_id=spec['source_file_id'],
            source_url=spec.get('source_url', ''),
            source_sheet=spec['source_sheet'],
            header_row=spec.get('header_row'),
            max_rows=MAX_ROWS_PER_SOURCE,
            include_sensitive=False,
        )
        records = result['records']
        normalized.append(result)
        totals['rows_scanned'] += len(rows)
        totals['records'] += len(records)
        totals['warnings'] += result['summary']['warning_count']
        totals['with_jan'] += sum(bool(r['jan_string']) for r in records)
        totals['with_asin'] += sum(bool(r['asin_candidate']) for r in records)
        totals['with_model'] += sum(bool(r['model_number']) for r in records)
        totals['cost_present'] += sum(bool(r['cost_present']) for r in records)
        totals['cost_tax_unknown'] += sum(
            r['cost_present'] and r['cost_tax_mode'] == 'unknown'
            for r in records)
        for warning in result['warnings']:
            if 'AMBIGUOUS_COLUMNS' in warning['codes']:
                for key in warning.get('fields', []):
                    ambiguous_field_source_counts[key] = (
                        ambiguous_field_source_counts.get(key, 0) + 1)
        for key in result['mapped_columns']:
            mapped_coverage[key] = mapped_coverage.get(key, 0) + 1

    return {
        'public_summary': {
            'source_count': len(normalized),
            'rows_scanned': totals['rows_scanned'],
            'record_count': totals['records'],
            'warning_count': totals['warnings'],
            'records_with_jan': totals['with_jan'],
            'records_with_asin': totals['with_asin'],
            'records_with_model': totals['with_model'],
            'records_with_cost_field': totals['cost_present'],
            'records_cost_tax_unknown': totals['cost_tax_unknown'],
            'mapped_source_counts': dict(sorted(mapped_coverage.items())),
            'ambiguous_field_source_counts': dict(
                sorted(ambiguous_field_source_counts.items())),
            'confirmed_product_matches': 0,
            'profit_calculation_allowed': False,
            'purchase_allowed': False,
            'source_writes': 0,
            'api_calls': 0,
        },
        'private_normalized_docs': normalized,
    }



def validate_source_lookup(field, query):
    """Validate a private lookup BEFORE any data read in a connector bridge."""
    key = LOOKUP_ALIASES.get(field, field) if isinstance(field, str) else None
    if key not in LOOKUP_FIELDS or not isinstance(query, str):
        raise ValueError('unsupported lookup field or query')
    needle = _text(query)
    if len(needle) < 3 or len(needle) > 120:
        raise ValueError('search query must be 3-120 characters')
    if key == 'jan_string' and not _JAN.fullmatch(query.strip()):
        raise ValueError('JAN lookup requires exact 8-14 ASCII digits')
    if key == 'asin_candidate' and not _ASIN.fullmatch(query.strip().upper()):
        raise ValueError('ASIN lookup requires a 10-character alphanumeric ID')
    return key, needle


def search_selected_sources(normalized, *, field, query):
    """Search local PRIVATE normalized documents; no automatic Drive scan.

    Exact match for JAN/ASIN, case/width-insensitive substring for
    names/models. Results are PRIVATE source/row indexes, with no product
    values echoed. An unsearched source cannot be declared nonexistent.
    """
    if (not isinstance(normalized, dict)
            or not isinstance(normalized.get('private_normalized_docs'), list)):
        raise ValueError('normalized private documents required')
    docs = normalized['private_normalized_docs']
    if not 1 <= len(docs) <= MAX_SOURCES:
        raise ValueError('invalid selected source count')
    key, needle = validate_source_lookup(field, query)

    hits = []
    # Bound cumulative iteration and returned evidence. If too many hits,
    # state truncation; never silently claim complete search.
    examined = 0
    for source_index, doc in enumerate(docs):
        for row_index, record in enumerate(doc['records']):
            examined += 1
            raw_value = record.get(key, '')
            if key == 'asin_candidate':
                # Do not lose multi-ASIN candidates that parser preserved.
                pool = record.get('asin_candidates', [])
                matched = query.strip().upper() in pool
            elif key == 'jan_string':
                matched = query.strip() == raw_value
            else:
                matched = needle in _text(raw_value)
            if matched and len(hits) < MAX_SEARCH_HITS:
                hits.append({
                    'source_index': source_index,
                    'record_index': row_index,
                    'source_row': record['source_row'],
                    'match_field': key,
                })
    matches_capped = examined >= 0 and sum(
        1 for doc in docs for record in doc['records']
        if (query.strip().upper() in record.get('asin_candidates', [])
            if key == 'asin_candidate'
            else query.strip() == record.get(key, '')
            if key == 'jan_string'
            else needle in _text(record.get(key, '')))
    ) > MAX_SEARCH_HITS

    return {
        'public_summary': {
            'sources_searched': len(docs),
            'records_examined': examined,
            'hits_returned': len(hits),
            'results_truncated': matches_capped,
            'all_supplier_folders_searched': False,
            'product_identity_confirmed': False,
            'profit_calculation_allowed': False,
            'source_writes': 0,
            'api_calls': 0,
        },
        'private_hits': hits,
    }
