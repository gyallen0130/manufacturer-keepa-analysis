"""Offline, read-only candidate comparison across supplier documents.

Consumes private, already-normalized rows (including parser.parse_rows records).
Never calls APIs, evaluates formulas, changes source data or confirms a saleable SKU.
Caller must keep private_pairs private; only public_summary is log-safe.
"""
from collections import Counter
import re
import unicodedata

MAX_RECORDS_PER_SIDE = 200
MAX_ASINS_PER_RECORD = 10
STATUSES = (
    'strong_candidate', 'id_candidate', 'name_only',
    'conflict', 'insufficient',
)
_ASIN = re.compile(r'^[A-Z0-9]{10}$')
_DIGITS = re.compile(r'^[0-9]+$')
_SPACE = re.compile(r'\s+')


def _text(value):
    if not isinstance(value, str):
        return ''
    return _SPACE.sub(' ', unicodedata.normalize('NFKC', value).strip()).casefold()


def _gtin(value):
    """Preserve exact string digits and length; reject lost leading zeros."""
    if not isinstance(value, str):
        return ''
    raw = value.strip()
    if len(raw) not in (8, 12, 13, 14) or not _DIGITS.fullmatch(raw):
        return ''
    numbers = [int(c) for c in raw]
    checksum = (10 - sum(
        d * (3 if (len(numbers) - i) % 2 == 0 else 1)
        for i, d in enumerate(numbers[:-1])
    ) % 10) % 10
    return raw if checksum == numbers[-1] else ''


def _asins(row):
    sources = [row.get('asin_candidate', ''), row.get('asin', '')]
    extra = row.get('asin_candidates', [])
    if extra is None:
        extra = []
    if not isinstance(extra, (list, tuple)) or len(extra) > MAX_ASINS_PER_RECORD:
        raise ValueError('invalid ASIN candidate list')
    sources.extend(extra)
    codes = set()
    for val in sources:
        if not isinstance(val, str) or not val.strip():
            continue
        value = val.strip().upper()
        if _ASIN.fullmatch(value):
            codes.add(value)
    return frozenset(codes)


def _normal(row):
    return {
        'jan': _gtin(row.get('jan_string', row.get('jan'))),
        'asins': _asins(row),
        'name': _text(row.get('product_name_raw') or row.get('product_name')
                      or row.get('product_name_amazon') or row.get('amazon_name')),
        'model': _text(row.get('model_number') or row.get('model_number_raw')),
        'pack': _text(row.get('pack_quantity')),  # NOT order_multiple (purchase lot).
        'size': _text(row.get('capacity') or row.get('size')),
        'ambiguous_asin': len(_asins(row)) > 1,
    }


def _classify(a, b):
    same_jan = bool(a['jan'] and a['jan'] == b['jan'])
    shared_asin = bool(a['asins'] & b['asins'])
    same_name = bool(a['name'] and a['name'] == b['name'])
    evidence = []
    if same_jan:
        evidence.append('jan_exact')
    if shared_asin:
        evidence.append('asin_exact')
    if same_name:
        evidence.append('name_exact')

    if not (same_jan or shared_asin or same_name):
        return None

    conflict = False
    if a['jan'] and b['jan'] and not same_jan:
        conflict = True
        evidence.append('jan_mismatch')
    if a['asins'] and b['asins'] and not shared_asin:
        conflict = True
        evidence.append('asin_mismatch')
    if a['name'] and b['name'] and not same_name:
        conflict = True
        evidence.append('name_mismatch')
    for key in ('model', 'pack', 'size'):
        if a[key] and b[key] and a[key] != b[key]:
            conflict = True
            evidence.append(key + '_mismatch')

    if conflict:
        status = 'conflict'
    elif (same_jan and shared_asin and same_name and
          not a['ambiguous_asin'] and not b['ambiguous_asin']):
        status = 'strong_candidate'
    elif same_jan or shared_asin:
        status = 'id_candidate'
    else:
        status = 'name_only'

    if a['ambiguous_asin'] or b['ambiguous_asin']:
        evidence.append('ambiguous_asin')
    return {'status': status, 'evidence_codes': sorted(evidence)}


def compare_supplier_rows(left_records, right_records):
    """Match no more than 200 rows per document, with no external side effects.

    Public summary contains ONLY aggregate integers and status labels.
    Private pairs contain row indices and evidence codes, never raw values.
    An apparent strong match is downgraded if it has multiple partner rows.
    No status means confirmed SKU, valid contract or sourcing approval.
    """
    if (not isinstance(left_records, (list, tuple))
            or not isinstance(right_records, (list, tuple))
            or len(left_records) > MAX_RECORDS_PER_SIDE
            or len(right_records) > MAX_RECORDS_PER_SIDE
            or not all(isinstance(x, dict) for x in left_records)
            or not all(isinstance(x, dict) for x in right_records)):
        raise ValueError('invalid or oversized supplier record collection')

    left = [_normal(row) for row in left_records]
    right = [_normal(row) for row in right_records]
    pairs = []
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            classification = _classify(a, b)
            if classification is not None:
                pairs.append({
                    'left_index': i, 'right_index': j, **classification,
                })

    left_counts = Counter(p['left_index'] for p in pairs)
    right_counts = Counter(p['right_index'] for p in pairs)
    for pair in pairs:
        if (pair['status'] == 'strong_candidate'
                and (left_counts[pair['left_index']] > 1
                     or right_counts[pair['right_index']] > 1)):
            pair['status'] = 'id_candidate'
            pair['evidence_codes'].append('multiple_candidate_rows')
            pair['evidence_codes'].sort()

    statuses = Counter(p['status'] for p in pairs)
    return {
        'public_summary': {
            'source_a_rows': len(left), 'source_b_rows': len(right),
            'candidate_pairs': len(pairs),
            'unmatched_a_rows': len(left) - len(left_counts),
            'unmatched_b_rows': len(right) - len(right_counts),
            'status_counts': {key: statuses.get(key, 0) for key in STATUSES},
            'confirmed_saleable_skus': 0,
            'source_writes': 0,
            'api_calls': 0,
            'decision': 'human_review_required',
        },
        'private_pairs': pairs,
    }
