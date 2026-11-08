"""Explicit, review-only mapping for multi-row supplier sheet headers.

No automatic collapsing of tiered headers, prices, quantities, POS/ITF into
JAN, or supplier product identity. Caller must manually specify original
physical header coordinates for each safe, separately labelled field.

All returned records and provenance are PRIVATE. Do not log or commit them.
This module neither reads files nor makes network/credential calls.
"""
from collections import Counter

from .parser import (
    ALIASES, NORMALIZED_ALIASES, _asin_candidates, _identifier,
    normalize_header, SCHEMA_VERSION,
)

MAPPING_VERSION = 'tiered-review-v1'
# No cost_amount, order_multiple, tax, case quantity or profit columns here.
# Source-side product identifiers are strictly candidates.
ALLOWED_FIELDS = frozenset({
    'product_name_raw', 'jan_string', 'asin', 'model_number',
    'manufacturer_name_raw',
})
MAX_ROWS = 40
MAX_COLUMNS = 15


def validate_tiered_mapping_schema(mapping):
    """Pure structural preflight, usable BEFORE any API/file read."""
    if (not isinstance(mapping, dict)
            or set(mapping) != {'version', 'header_rows', 'data_start_row',
                                'fields'}
            or mapping['version'] != MAPPING_VERSION
            or not isinstance(mapping['header_rows'], list)
            or not 2 <= len(mapping['header_rows']) <= 4
            or any(type(x) is not int or not 1 <= x <= MAX_ROWS
                   for x in mapping['header_rows'])
            or len(set(mapping['header_rows'])) != len(mapping['header_rows'])
            or mapping['header_rows'] != sorted(mapping['header_rows'])
            or max(mapping['header_rows']) - min(mapping['header_rows']) > 5
            or type(mapping['data_start_row']) is not int
            or not max(mapping['header_rows']) < mapping['data_start_row'] <= MAX_ROWS
            or not isinstance(mapping['fields'], dict)
            or not 1 <= len(mapping['fields']) <= len(ALLOWED_FIELDS)
            or not set(mapping['fields']) <= ALLOWED_FIELDS
            or not any(k in mapping['fields']
                       for k in ('product_name_raw', 'jan_string', 'asin',
                                 'model_number'))
            or any(not isinstance(loc, dict)
                   or set(loc) != {'row', 'column'}
                   or type(loc['row']) is not int
                   or type(loc['column']) is not int
                   or loc['row'] not in mapping['header_rows']
                   or not 1 <= loc['column'] <= MAX_COLUMNS
                   for loc in mapping['fields'].values())):
        raise ValueError('invalid explicit tiered-header mapping')
    columns = [loc['column'] for loc in mapping['fields'].values()]
    if len(columns) != len(set(columns)):
        raise ValueError('a single mixed header column cannot map to two fields')
    return mapping


def _cell(rows, row, column):
    if row > len(rows):
        return None
    raw = rows[row - 1]
    return raw[column - 1] if column <= len(raw) else None


def _safe_text(value):
    if not isinstance(value, str) or value.lstrip().startswith('='):
        return ''
    return value.strip()


def map_explicit_tiered_headers(rows, mapping, *, document_type,
                                source_file_id, source_sheet, source_url=''):
    """Extract review-only candidates with exact header-cell provenance.

    The selected header cells must each be exact canonical label aliases.
    For instance a combined '商品名・POSコード・ITFコード' is NOT a valid
    product or JAN header, because product identifiers may be mixed.
    """
    validate_tiered_mapping_schema(mapping)
    if (not isinstance(rows, (list, tuple)) or len(rows) > MAX_ROWS
            or any(not isinstance(row, (list, tuple))
                   or len(row) > MAX_COLUMNS for row in rows)):
        raise ValueError('tiered source exceeds 40x15 window')
    if mapping['data_start_row'] > len(rows):
        raise ValueError('no selected data window after tiered headers')
    for key, pos in mapping['fields'].items():
        header = _cell(rows, pos['row'], pos['column'])
        # Verify the exact cell label, not a weak surrounding tier title.
        if (not isinstance(header, str)
                or normalize_header(header) not in NORMALIZED_ALIASES[key]):
            raise ValueError('manual mapping does not match an exact field label')

    records, warnings = [], []
    index = {field: pos['column'] for field, pos in mapping['fields'].items()}
    for row_number in range(mapping['data_start_row'], len(rows) + 1):
        raw_name = _cell(rows, row_number, index.get('product_name_raw', 16))
        product_name = _safe_text(raw_name)
        model = _safe_text(_cell(rows, row_number, index.get('model_number', 16)))
        maker = _safe_text(_cell(rows, row_number, index.get('manufacturer_name_raw', 16)))
        jan_raw = _cell(rows, row_number, index.get('jan_string', 16))
        asin_raw = _cell(rows, row_number, index.get('asin', 16))
        if not any(x is not None and str(x).strip()
                   for x in (raw_name, jan_raw, asin_raw, model)):
            continue
        codes = []
        if 'jan_string' in index:
            jan, err = _identifier(jan_raw, kind='JAN')
            if err:
                codes.append(err)
        else:
            jan = ''
        if 'asin' in index:
            candidates, asin_errors = _asin_candidates(asin_raw)
            codes.extend(asin_errors)
        else:
            candidates = []
        if raw_name and not product_name:
            codes.append('UNSAFE_PRODUCT_TEXT')
        if codes:
            warnings.append({'row': row_number, 'codes': sorted(set(codes))})
        records.append({
            'source_file_id': source_file_id,
            'source_url': source_url,
            'source_sheet': source_sheet,
            'source_row': row_number,
            'document_type': document_type,
            'manufacturer_name_raw': maker,
            'manufacturer_code': '',
            'product_name_raw': product_name,
            'model_number': model,
            'jan_string': jan,
            'asin_candidate': candidates[0] if len(candidates) == 1 else '',
            'asin_candidates': candidates,
            'source_group': source_sheet,
            'trade_terms_present': False,
            'order_multiple': '',
            'cost_present': False,
            'cost_tax_mode': 'unknown',
            'source_profit_status': 'unclassified',
            'risk_codes': ['TIERED_HEADER_MANUAL_REVIEW',
                           'COST_UNKNOWN', 'UNIT_UNKNOWN', 'TAX_UNKNOWN'],
            'decision': 'needs_confirmation',
        })
    return {
        'schema_version': SCHEMA_VERSION,
        'document_type': document_type,
        'source_file_id': source_file_id,
        'source_url': source_url,
        'source_sheet': source_sheet,
        'header_row': None,
        'header_rows': list(mapping['header_rows']),
        'mapped_columns': dict(index),
        'mapped_header_cells': {field: {
            'row': position['row'], 'column': position['column'],
        } for field, position in mapping['fields'].items()},
        'inferred_columns': {},
        'summary': {
            'record_count': len(records),
            'risk_counts': dict(sorted(Counter(
                code for record in records for code in record['risk_codes']
            ).items())),
            'warning_count': len(warnings),
            'inferred_fields': [],
        },
        'warnings': warnings,
        'records': records,
    }
