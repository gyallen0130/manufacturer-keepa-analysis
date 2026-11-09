"""Read-only, explicit row-label candidate extraction from tiered price lists.

A row may contain POSコード: [barcode] and ITFコード: [barcode], even
though the worksheet has a multi-row header. They are NEVER silently
promoted to confirmed JAN, SKU, product name, price or a purchase unit.
This module only returns private candidate codes, original physical rows
and fail-closed warnings. No API, files, formulas or prices are accessed.
"""
from collections import Counter
import re
import unicodedata

from .parser import SCHEMA_VERSION

VERSION = 'row-label-review-v1'
ALLOWED = frozenset(('pos_candidate', 'itf_candidate'))
LABELS = {'pos_candidate': 'posコード', 'itf_candidate': 'itfコード'}
MAX_ROWS = 40
MAX_COLS = 15
DIGITS = re.compile(r'^[0-9]+$')


def _normalized_label(value):
    if not isinstance(value, str):
        return ''
    value = unicodedata.normalize('NFKC', value).casefold().strip()
    # Only strip adjacent whitespace and punctuation, not interior words.
    return re.sub(r'[\s:：]+$', '', re.sub(r'^\s+', '', value))


def valid_gtin_digits(value, *, kind):
    """Structural GS1 check digit check, NOT proof of brand/product identity."""
    if (not isinstance(value, str) or not DIGITS.fullmatch(value)
            or len(value) not in ((8, 12, 13) if kind == 'pos_candidate' else (14,))):
        return False
    numbers = [int(c) for c in value]
    checksum = sum(
        digit * (3 if index % 2 == 0 else 1)
        for index, digit in enumerate(reversed(numbers[:-1])))
    return (10 - checksum % 10) % 10 == numbers[-1]


def validate_row_label_mapping(mapping):
    """Reject unknown roles, stale schema, path data and overlapping columns."""
    if (not isinstance(mapping, dict)
            or set(mapping) != {'version', 'data_start_row', 'fields'}
            or mapping['version'] != VERSION
            or type(mapping['data_start_row']) is not int
            or not 2 <= mapping['data_start_row'] <= MAX_ROWS
            or not isinstance(mapping['fields'], dict)
            or not 1 <= len(mapping['fields']) <= len(ALLOWED)
            or not set(mapping['fields']) <= ALLOWED):
        raise ValueError('invalid row-label candidate mapping')
    occupied = set()
    for kind, spec in mapping['fields'].items():
        if (not isinstance(spec, dict)
                or set(spec) != {'label_column', 'value_column'}
                or type(spec['label_column']) is not int
                or type(spec['value_column']) is not int
                or not 1 <= spec['label_column'] < MAX_COLS
                or spec['value_column'] != spec['label_column'] + 1):
            raise ValueError('labels must be adjacent to distinct candidate columns')
        positions = (spec['label_column'], spec['value_column'])
        if any(pos in occupied for pos in positions):
            raise ValueError('candidate columns overlap')
        occupied.update(positions)
    return mapping


def _cell(row, col):
    return row[col - 1] if col <= len(row) else None


def extract_row_labeled_candidates(rows, mapping, *, document_type,
                                   source_file_id, source_sheet, source_url=''):
    """Find exact row-anchored POS/ITF candidate pairs in bounded rows.

    A numeric cell is never auto-converted to a barcode (leading zeros can
    disappear), nor are formula strings or invalid checksums accepted.
    Even a valid POS/GTIN-13 is NOT automatically a confirmed JAN.
    """
    validate_row_label_mapping(mapping)
    if (not isinstance(rows, (list, tuple)) or len(rows) > MAX_ROWS
            or any(not isinstance(row, (list, tuple))
                   or len(row) > MAX_COLS for row in rows)):
        raise ValueError('row-label window exceeds 40x15')
    if mapping['data_start_row'] > len(rows):
        raise ValueError('row-label data start outside selected window')
    records, warnings = [], []
    label_match_rows = 0
    for row_index in range(mapping['data_start_row'] - 1, len(rows)):
        row = rows[row_index]
        values, codes, labels_here = {}, [], 0
        for kind, cols in mapping['fields'].items():
            label = _cell(row, cols['label_column'])
            if _normalized_label(label) != LABELS[kind]:
                continue
            labels_here += 1
            raw_value = _cell(row, cols['value_column'])
            if raw_value is None or str(raw_value).strip() in ('', '-', '－', '0'):
                codes.append('LABELED_IDENTIFIER_EMPTY')
            elif not isinstance(raw_value, str):
                codes.append('NUMERIC_BARCODE_NOT_TRUSTED')
            elif raw_value.lstrip().startswith('='):
                codes.append('BARCODE_FORMULA_NOT_TRUSTED')
            else:
                candidate = unicodedata.normalize('NFKC', raw_value).strip()
                if valid_gtin_digits(candidate, kind=kind):
                    values[kind] = candidate
                else:
                    codes.append('BARCODE_FORMAT_OR_CHECKSUM_UNVERIFIED')
        if labels_here:
            label_match_rows += 1
        if codes:
            warnings.append({'row': row_index + 1, 'codes': sorted(set(codes))})
        if not values:
            continue
        records.append({
            'source_file_id': source_file_id,
            'source_url': source_url,
            'source_sheet': source_sheet,
            'source_row': row_index + 1,
            'document_type': document_type,
            'manufacturer_name_raw': '',
            'manufacturer_code': '',
            'product_name_raw': '',
            'model_number': '',
            'jan_string': '',
            'pos_candidate': values.get('pos_candidate', ''),
            'itf_candidate': values.get('itf_candidate', ''),
            'asin_candidate': '',
            'asin_candidates': [],
            'source_group': source_sheet,
            'trade_terms_present': False,
            'order_multiple': '',
            'cost_present': False,
            'cost_tax_mode': 'unknown',
            'source_profit_status': 'unclassified',
            'risk_codes': [
                'ROW_LABELED_IDENTIFIER_REVIEW', 'PRODUCT_IDENTITY_UNKNOWN',
                'COST_UNKNOWN', 'UNIT_UNKNOWN', 'TAX_UNKNOWN',
            ],
            'decision': 'needs_confirmation',
        })
    return {
        'schema_version': SCHEMA_VERSION,
        'document_type': document_type,
        'source_file_id': source_file_id,
        'source_url': source_url,
        'source_sheet': source_sheet,
        'source_status': 'labeled_review' if records else 'needs_review',
        'header_row': None,
        'mapped_columns': {},
        'mapped_row_labels': {
            kind: dict(spec) for kind, spec in mapping['fields'].items()},
        'inferred_columns': {},
        'summary': {
            'record_count': len(records),
            'label_match_rows': label_match_rows,
            'warning_count': len(warnings),
            'risk_counts': dict(sorted(Counter(
                code for record in records for code in record['risk_codes']
            ).items())),
            'inferred_fields': [],
        },
        'warnings': warnings,
        'records': records,
    }
