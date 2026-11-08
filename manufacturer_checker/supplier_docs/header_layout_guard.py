"""Bounded, read-only preflight for supplier header geometry.

Inputs are already authorized rows from Sheets or Excel; only structural
metadata is returned. Does not extract, echo, or score product identifiers,
prices, supplier names or contact details. Multi-row headers are NOT
automatically collapsed into invented cost/quantity fields.
"""
import re
import unicodedata

MAX_HEADER_ROWS = 40
MAX_HEADER_COLS = 15

ALIASES = {
    'product_name': {'商品名', '品名', '製品名'},
    'jan': {'jan', 'janコード', 'ean', 'eanコード'},
    'asin': {'asin'},
    'model': {'型番', '品番', 'メーカー品番', '商品コード'},
    'price_hint': {'単価', '価格', '卸値', '卸値税込', '卸値税抜',
                   '下代', '下代税込', '下代税抜', '定価', '上代税抜',
                   '上代税込', '卸価格', '税込仕入れ値'},
    'quantity_hint': {'入数', 'ケース入数', '発注単位', '発注ロット'},
}


def _normalize(value):
    text = unicodedata.normalize('NFKC', value).casefold()
    return re.sub(r'[\s\-_/():：（）]+', '', text)


def _type(value):
    if not isinstance(value, str):
        return None
    t = _normalize(value)
    if not t or t.startswith('='):
        return None
    for kind, aliases in ALIASES.items():
        if t in aliases:
            return kind
    # Some price lists group product name, POS code and ITF in ONE label.
    # Such a group is not a verified JAN/GTIN field.
    if '商品名' in t and ('posコード' in t or 'itfコード' in t):
        return 'product_name'
    return None


def inspect_header_layout(rows):
    """Classify header geometry; return only anonymous, non-product facts.

    - single_row: one confident header line. Metadata is NOT a product match.
    - multi_row_needs_review: multiple adjacent header tiers; no price mapping.
    - no_reliable_header/empty: do not silently assume the first line is header.

    Strict limits prevent expensive scans and avoid copying whole price lists.
    """
    if (not isinstance(rows, (list, tuple))
            or len(rows) > MAX_HEADER_ROWS
            or any(not isinstance(row, (list, tuple))
                   or len(row) > MAX_HEADER_COLS for row in rows)):
        raise ValueError('header preflight requires at most 40x15 cells')
    candidates = []
    for physical_row, row in enumerate(rows, 1):
        types = [(_type(cell), index) for index, cell in enumerate(row)]
        classified = [(kind, index) for kind, index in types if kind]
        if classified:
            candidates.append((physical_row, classified))
    if not any(any(cell is not None and str(cell).strip() for cell in row)
               for row in rows):
        status, chosen, header_span = 'empty', None, None
    else:
        strong = []
        for r, matches in candidates:
            kinds = {kind for kind, _ in matches}
            if ('product_name' in kinds
                    and (kinds & {'jan', 'asin', 'model', 'price_hint'})):
                strong.append((len(kinds), len(matches), r, matches))
        if strong:
            _, _, chosen, matches = max(
                strong, key=lambda item: (item[0], item[1], -item[2]))
            status, header_span = 'single_row', None
        else:
            header_span = None
            for start in range(1, MAX_HEADER_ROWS - 2):
                cluster = [(r, m) for r, m in candidates
                           if start <= r <= start + 3]
                fields = {kind for _, hits in cluster for kind, _ in hits}
                if (len({r for r, _ in cluster}) >= 2
                        and 'product_name' in fields
                        and len(fields) >= 3
                        and fields & {'quantity_hint', 'price_hint'}):
                    header_span = (min(r for r, _ in cluster),
                                   max(r for r, _ in cluster))
                    break
            status = ('multi_row_needs_review' if header_span
                      else 'no_reliable_header')
            chosen, matches = None, []

    warnings = []
    if status == 'single_row':
        if sum(kind == 'jan' for kind, _ in matches) > 1:
            warnings.append('duplicate_jan_heading')
        if sum(kind == 'price_hint' for kind, _ in matches) > 1:
            warnings.append('multiple_price_hints')
    return {
        'status': status,
        'header_row': chosen,
        'header_span': list(header_span) if header_span else None,
        'heading_categories': sorted({kind for kind, _ in matches}),
        'warnings': warnings,
        'source_writes': 0,
        'product_values_returned': 0,
        'prices_returned': 0,
    }
