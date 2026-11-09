"""Combine already-normalized private Excel and Google Sheets windows.

No Drive discovery, authentication, file reads, new network I/O, merging
source rows, SKU conversion, price calculation or persistence takes place.
Source rows, identities, paths and matching identifiers remain PRIVATE.
Only bounded anonymous counts are returned in public_summary.
"""
from collections import Counter

from .multi_source_readonly import (
    MAX_SOURCES, search_selected_sources, validate_source_lookup,
)

SUPPORTED = {
    ('manual-local-excel-v1', 'manual_local_excel_readonly'): 'excel',
    ('manual-multi-sheet-v1', 'manual_readonly'): 'sheets',
    ('manual-connector-sheet-snapshot-v1', 'manual_snapshot_readonly'): 'sheets',
}
MAX_RECORDS_PER_DOC = 40
SOURCE_STATUSES = frozenset({
    'parsed', 'mapped_review', 'labeled_review', 'needs_review', 'empty',
})


def combine_selected_source_results(results, *, search=None):
    """Combine exactly one Excel result and one Sheets result, max 5 tabs.

    Inputs must be the PRIVATE return values of the authorized existing
    bridges. Use the same calling environment and never log returned
    private_normalized_docs, private_hits or private_origin_manifest.
    """
    if not isinstance(results, list) or len(results) != 2:
        raise ValueError('select one Excel result and one Sheets result')
    if search is not None:
        if not isinstance(search, dict) or set(search) != {'field', 'query'}:
            raise ValueError('invalid private mixed-source search')
        validate_source_lookup(search['field'], search['query'])

    docs, source_kinds, source_origins, seen = [], [], [], set()
    formats = set()
    api_calls = 0
    for original in results:
        if not isinstance(original, dict):
            raise ValueError('invalid private normalized bridge result')
        summary = original.get('public_summary')
        section = original.get('private_normalized_docs')
        if not isinstance(summary, dict) or not isinstance(section, list):
            raise ValueError('source metadata or private rows missing')
        key = (summary.get('schema_version'), summary.get('mode'))
        if key not in SUPPORTED:
            raise ValueError('unexpected normalized result version')
        kind = SUPPORTED[key]
        if kind in formats:
            raise ValueError('duplicate bridge type')
        formats.add(kind)
        if (type(summary.get('source_count')) is not int
                or summary['source_count'] != len(section)
                or not 1 <= len(section) <= MAX_SOURCES
                or summary.get('source_writes') != 0
                or summary.get('profit_calculation_allowed') is not False
                or summary.get('purchase_allowed') is not False):
            raise ValueError('unsafe or inconsistent source summary')
        if (type(summary.get('api_calls')) is not int
                or not 0 <= summary['api_calls'] <= 20):
            raise ValueError('unexpected bridge API activity')
        api_calls += summary['api_calls']
        origins = original.get('private_origin_manifest')
        if kind == 'excel':
            if (not isinstance(origins, list)
                    or len(origins) != len(section)):
                raise ValueError('Excel source origin mapping unavailable')
        elif origins is not None:
            raise ValueError('unexpected Sheets origin mapping')
        for index, doc in enumerate(section):
            if (not isinstance(doc, dict)
                    or doc.get('source_status') not in SOURCE_STATUSES
                    or not isinstance(doc.get('source_file_id'), str)
                    or not isinstance(doc.get('source_sheet'), str)
                    or not isinstance(doc.get('records'), list)
                    or len(doc['records']) > MAX_RECORDS_PER_DOC):
                raise ValueError('invalid bounded private source document')
            unique = (kind, doc['source_file_id'], doc['source_sheet'])
            if unique in seen:
                raise ValueError('duplicate selected source')
            seen.add(unique)
            for record in doc['records']:
                if (not isinstance(record, dict)
                        or type(record.get('source_row')) is not int
                        or not 1 <= record['source_row'] <= 40
                        or record.get('source_file_id') != doc['source_file_id']
                        or record.get('source_sheet') != doc['source_sheet']):
                    raise ValueError('invalid original-row provenance')
            if kind == 'excel':
                origin = origins[index]
                if (not isinstance(origin, dict)
                        or set(origin) != {
                            'relative_path', 'sheet_name', 'source_file_id'
                        }
                        or origin['source_file_id'] != doc['source_file_id']
                        or origin['sheet_name'] != doc['source_sheet']
                        or not isinstance(origin['relative_path'], str)
                        or not 1 <= len(origin['relative_path']) <= 300):
                    raise ValueError('Excel source origin mapping mismatch')
                selected_origin = {
                    'source_kind': 'excel',
                    'relative_path': origin['relative_path'],
                    'source_sheet': doc['source_sheet'],
                }
            else:
                selected_origin = {
                    'source_kind': 'sheets',
                    'source_url': doc.get('source_url', ''),
                    'source_sheet': doc['source_sheet'],
                }
            docs.append(doc)
            source_kinds.append(kind)
            source_origins.append(selected_origin)
    if len(docs) > MAX_SOURCES:
        raise ValueError('combined read exceeds five approved tabs')

    statuses = Counter(doc['source_status'] for doc in docs)
    fields = {
        'jan': 'jan_string',
        'asin': 'asin_candidate',
        'model': 'model_number',
        'pos': 'pos_candidate',
        'itf': 'itf_candidate',
    }
    flat = [row for d in docs for row in d['records']]
    summary = {
        'schema_version': 'manual-mixed-sources-v1',
        'mode': 'manual_readonly',
        'source_count': len(docs),
        'source_kind_counts': {kind: source_kinds.count(kind)
                               for kind in ('excel', 'sheets')},
        'source_status_counts': {status: statuses[status]
                                 for status in ('parsed', 'mapped_review',
                                                'labeled_review',
                                                'needs_review', 'empty')},
        'sources_not_searchable': statuses['needs_review'] + statuses['empty'],
        'all_selected_windows_parsed': statuses['parsed'] == len(docs),
        'record_count': len(flat),
        'records_by_identifier_kind': {
            kind: sum(bool(row.get(key)) for row in flat)
            for kind, key in fields.items()
        },
        'confirmed_product_matches': 0,
        'profit_calculation_allowed': False,
        'purchase_allowed': False,
        'source_writes': 0,
        'api_calls': api_calls,
        'all_supplier_folders_searched': False,
    }
    merged = {
        'public_summary': summary,
        'private_normalized_docs': docs,
        'private_source_kinds': source_kinds,
        # The original file path / Sheet URL never enters public_summary.
        # It is used only by a separately opted-in PRIVATE viewer.
        'private_source_origins': source_origins,
    }
    if search is not None:
        found = search_selected_sources(merged, **search)
        merged['public_search_summary'] = found['public_summary']
        merged['private_hits'] = found['private_hits']
    return merged
