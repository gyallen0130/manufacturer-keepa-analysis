"""Conservative offline audit of repeated JAN headers in supplier quote tables.

All column positions are explicitly selected by the caller. No inference about
which JAN is authoritative, current availability, or eligible Amazon SKU.
No Google/Keepa requests, filesystem writes, logs, prices or SKU identifiers
in the output. Use only in an authorized private data processing context.
"""
from collections import Counter
import unicodedata

MAX_ROWS = 250
MAX_COLUMNS = 32
HISTORICAL_UNAVAILABLE = frozenset({
    '廃番', '廃盤', '取扱終了', '取り扱い終了', '生産終了',
})
CODES = (
    'same_as_displayed',
    'different_as_displayed',
    'historical_unavailable_note',
    'missing_or_unreadable',
)


def _word(value):
    return unicodedata.normalize('NFKC', str(value or '')).strip()


def _display_code(value):
    # Exact printable digits only, even if originally stored as a number.
    # Comparing a numeric display does NOT recover leading zeroes or prove GTIN.
    if isinstance(value, bool):
        return ''
    if isinstance(value, str):
        v = value.strip()
        return v if v.isascii() and v.isdecimal() and 8 <= len(v) <= 14 else ''
    if isinstance(value, int) and 0 <= value < 10**14:
        return str(value) if 8 <= len(str(value)) <= 14 else ''
    return ''


def inspect_explicit_jan_columns(
        rows, *, header_row_index, request_jan_column, reply_jan_column,
        reply_note_columns=()):
    """Inspect one selected table without ever choosing a canonical JAN.

    All indices are zero-based, including header_row_index.
    "request" and "reply" are provisional caller-assigned *positions*, not
    verified commercial roles. The function never infers their meaning.
    Returns a safe aggregate summary and private row-number status codes.
    """
    if (not isinstance(rows, (list, tuple)) or len(rows) > MAX_ROWS
            or not all(isinstance(r, (list, tuple)) and len(r) <= MAX_COLUMNS
                       for r in rows)
            or not isinstance(header_row_index, int)
            or not 0 <= header_row_index < len(rows)
            or not isinstance(request_jan_column, int)
            or not isinstance(reply_jan_column, int)
            or request_jan_column == reply_jan_column
            or min(request_jan_column, reply_jan_column) < 0
            or max(request_jan_column, reply_jan_column) >= MAX_COLUMNS
            or not isinstance(reply_note_columns, (list, tuple))
            or len(reply_note_columns) > 8
            or any(not isinstance(i, int) or i < 0 or i >= MAX_COLUMNS
                   for i in reply_note_columns)):
        raise ValueError('invalid or oversized explicitly selected JAN table')
    h = rows[header_row_index]
    for col in (request_jan_column, reply_jan_column):
        if col >= len(h) or _word(h[col]).casefold() != 'jan':
            raise ValueError('expected two explicitly selected JAN headings')

    evidence = []
    for pos in range(header_row_index + 1, len(rows)):
        row = rows[pos]
        if not any(_word(cell) for cell in row):
            continue
        a = row[request_jan_column] if request_jan_column < len(row) else None
        b = row[reply_jan_column] if reply_jan_column < len(row) else None
        ca, cb = _display_code(a), _display_code(b)
        observed_notes = [
            _word(row[i]) for i in reply_note_columns if i < len(row)
        ]
        old_status = any(note in HISTORICAL_UNAVAILABLE
                         for note in observed_notes)
        numeric_cells = sum(type(x) is int for x in (a, b))
        if old_status:
            status = 'historical_unavailable_note'
        elif ca and cb and ca == cb:
            status = 'same_as_displayed'
        elif ca and cb and ca != cb:
            status = 'different_as_displayed'
        else:
            status = 'missing_or_unreadable'
        codes = [status]
        if numeric_cells:
            codes.append('numeric_jan_needs_original_format_review')
        evidence.append({
            'physical_row': pos + 1,
            'status': status,
            'review_codes': sorted(codes),
            # Duplicated headings are unresolved even where display matches.
            'jan_source_ambiguous': True,
        })

    counts = Counter(x['status'] for x in evidence)
    return {
        'public_summary': {
            'rows_compared': len(evidence),
            'status_counts': {name: counts.get(name, 0) for name in CODES},
            'jan_header_roles_verified': False,
            'confirmed_saleable_skus': 0,
            'requires_human_review': True,
            'source_writes': 0,
            'api_calls': 0,
        },
        'private_row_evidence': evidence,
    }


def attach_jan_audit_to_records(records, *, physical_row_numbers, audit):
    """Attach review flags by explicitly mapped physical row, never by guess.

    Missing, duplicate, or out-of-audit row numbers fail closed before
    producing any annotated record. Neither inputs nor source values mutate.
    """
    rows = audit.get('private_row_evidence') if isinstance(audit, dict) else None
    if (not isinstance(records, (list, tuple))
            or not isinstance(physical_row_numbers, (list, tuple))
            or len(records) != len(physical_row_numbers)
            or len(records) > MAX_ROWS
            or not isinstance(rows, list)
            or not all(isinstance(x, dict) for x in records)
            or any(type(n) is not int or n <= 0 for n in physical_row_numbers)
            or len(set(physical_row_numbers)) != len(physical_row_numbers)):
        raise ValueError('explicit supplier row mapping required')
    by_row = {item['physical_row']: item for item in rows}
    if len(by_row) != len(rows) or any(n not in by_row for n in physical_row_numbers):
        raise ValueError('unverified physical supplier row index')
    return [
        {**rec, 'jan_source_ambiguous': True,
         'supplier_quote_review_codes': list(by_row[n]['review_codes'])}
        for rec, n in zip(records, physical_row_numbers)
    ]
