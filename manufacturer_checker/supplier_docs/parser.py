"""Conservative normalization of supplier document rows; no network or side effects.

This parser never decides whether an item is legal to sell or profitable to source.
Input rows are *untrusted* values from a document; formulas are never evaluated.
"""
from collections import Counter
from decimal import Decimal, InvalidOperation
import re
import unicodedata

SCHEMA_VERSION = 'draft-0.1'
DOCUMENT_TYPES = frozenset({
    'manufacturer_list', 'quote_request', 'quote_response', 'catalog',
    'price_revision',
})

ALIASES = {
    'manufacturer_name_raw': ('メーカー', 'メーカー名', '取扱メーカー', '製造元'),
    'manufacturer_code': ('メーカーコード',),
    'product_name_raw': ('商品名', '品名', '製品名', '対象製品一覧', 'メーカー商品名'),
    'amazon_name': ('商品名(Amazon)', 'Amazon商品名'),
    'jan_string': ('JAN', 'JANコード', 'JAN/EAN', 'EAN', 'EANコード', 'バーコード'),
    'asin': ('ASIN',),
    'model_number': ('品番', '型番', 'メーカー品番'),
    'category': ('カテゴリ', 'カテゴリー', '分類'),
    'order_multiple': ('発注単位', '発注ロット', '最低発注単位'),
    'cost_amount': ('下代(税抜)', '下代(税込)', '下代',
                    '卸値(税抜)', '卸値(税込)', '卸値', '仕入価格', '仕入単価'),
    'source_profit_label': ('利益', '利益区分', '利益判定', '仕入判定'),
    'notes': ('備考', '販売制限', '注意事項'),
    'trade_terms': ('取引条件', '注文条件', '支払条件'),
    'trade_marker': ('取引', '取引可否'),
    'revision_before': ('変更前価格(税抜)', '変更前価格(税込)'),
    'revision_after': ('変更後価格(税抜)', '変更後価格(税込)'),
}

RISKS = {
    'CHANNEL_RESTRICTION': re.compile(r'(?:EC(?:サイト|販売)?|ネット(?:通販|販売)?|Amazon(?:販売)?|アマゾン(?:販売)?)(?:での)?(?:は)?(?:不可|禁止|NG)', re.I),
    'SUPPLY_RESTRICTION': re.compile(r'(?:取扱[い]?不可|取り扱い不可|美容ルート限定|直送(?:対応)?のみ|取扱対象外)'),
    'PRICE_POLICY_NOTE': re.compile(r'(?:定価販売|価格(?:厳守|維持)|売価(?:厳守|維持))'),
    'LOT_CONDITION': re.compile(r'(?:ケース単位|ロット(?:単位|発注)|[0-9０-９]+ケース以上)'),
    'MIN_ORDER_CONDITION': re.compile(r'(?:[0-9０-９,，]+\s*(?:円|ケース)\s*(?:\([^)]*\))?\s*以上)'),
}
ASIN = re.compile(r'^[A-Z0-9]{10}$')
JAN = re.compile(r'^[0-9]{8,14}$')


def normalize_header(v):
    text = unicodedata.normalize('NFKC', str(v or '')).casefold()
    return re.sub(r'[\s_\-・/()\[\]:：]+', '', text)


NORMALIZED_ALIASES = {key: {normalize_header(k) for k in aliases} for key, aliases in ALIASES.items()}


def _text(value):
    if value is None:
        return ''
    return unicodedata.normalize('NFKC', str(value)).strip()


def _mapping(header, document_type):
    tokens = [normalize_header(x) for x in header]
    mapping, ambiguity = {}, []
    for field, aliases in NORMALIZED_ALIASES.items():
        ix = [i for i, token in enumerate(tokens) if token and token in aliases]
        if len(ix) == 1:
            mapping[field] = ix[0]
        elif len(ix) > 1:
            ambiguity.append(field)
    if document_type == 'manufacturer_list' and not _text(header[0] if header else '') and 'manufacturer_code' in mapping:
        mapping['manufacturer_name_raw'] = 0
    return mapping, ambiguity


def _header_score(mapping, document_type):
    anchors = ('manufacturer_name_raw', 'product_name_raw', 'jan_string', 'manufacturer_code',
               'order_multiple', 'cost_amount', 'revision_after')
    count = sum(field in mapping for field in anchors)
    if document_type == 'manufacturer_list':
        return count if 'manufacturer_name_raw' in mapping or 'manufacturer_code' in mapping else 0
    return count if ('product_name_raw' in mapping or 'jan_string' in mapping) else 0


def _read_column(row, mapping, key):
    i = mapping.get(key)
    if i is None or i >= len(row):
        return ''
    value = row[i]
    if isinstance(value, str) and value.lstrip().startswith('='):
        return ''  # Never evaluate or propagate formulas as values.
    return _text(value)


def _is_numeric_cell(value):
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _identifier(value, *, kind):
    if value in ('', None):
        return '', None
    if isinstance(value, bool):
        return '', f'{kind}_INVALID'
    numeric_cell = _is_numeric_cell(value)
    if numeric_cell:
        try:
            dec = Decimal(str(value))
            if not dec.is_finite() or dec != dec.to_integral_value():
                return '', f'{kind}_INVALID'
            t = str(int(dec))
        except (InvalidOperation, OverflowError):
            return '', f'{kind}_INVALID'
    else:
        t = _text(value)
    if isinstance(value, str) and t.lstrip().startswith('='):
        return '', f'{kind}_FORMULA'
    invisible = any(ch in t for ch in ('\u200b', '\u2060', '\ufeff'))
    t = re.sub(r'[\s\-\u200b\u2060\ufeff]', '', t).upper()
    valid = JAN if kind == 'JAN' else ASIN
    if not valid.fullmatch(t):
        return '', f'{kind}_INVALID'
    if invisible and kind == 'JAN':
        return t, 'JAN_INVISIBLE_CHARACTER'
    return t, f'{kind}_NUMERIC_CELL' if numeric_cell and kind == 'JAN' else None


def _asin_candidates(value):
    """Preserve every distinct candidate; never pick a single ASIN from a multi-cell."""
    if value in ('', None):
        return [], []
    if not isinstance(value, str):
        return [], ['ASIN_INVALID']
    if value.lstrip().startswith('='):
        return [], ['ASIN_FORMULA']
    raw = _text(value).upper()
    parts = [part for part in re.split(r'[\s,，;；、]+', raw) if part]
    good = list(dict.fromkeys(part for part in parts if ASIN.fullmatch(part)))
    invalid = any(not ASIN.fullmatch(part) for part in parts)
    errors = []
    if invalid:
        errors.append('ASIN_PARTIALLY_INVALID' if good else 'ASIN_INVALID')
    if len(good) > 1:
        errors.append('ASIN_MULTIPLE_CANDIDATES')
    return good, errors


def _amount(value):
    if value in (None, ''):
        return None
    v = _text(value).replace(',', '').replace('￥', '').replace('¥', '')
    if not re.fullmatch(r'-?\d+(?:\.\d+)?', v):
        return None
    try:
        n = Decimal(v)
        if not n.is_finite() or n < 0:
            return None
        return str(n)
    except InvalidOperation:
        return None


def _profit_label(label):
    t = _text(label).replace(' ', '')
    if not t:
        return 'unknown'
    if t == '赤字':
        return 'red'
    if t == '黒字':
        return 'black'
    if t == '微黒字':
        return 'slight_black'
    return 'conditional_or_unclassified' if any(x in t for x in ('黒字', '赤字', '利益')) else 'unknown'



def _infer_unlabeled_columns(raw, header_index, mapping, document_type):
    """Infer only high-consensus, *unlabeled* ASIN/profit columns in quote sheets.

    This is structural inference, NOT ASIN verification or a profitability decision.
    Low-sample, sparse, mixed or competing columns remain unmapped. All inferred
    values must be flagged for source review.
    """
    if document_type not in ('quote_request', 'quote_response'):
        return {}, []
    header = raw[header_index]
    sample = []
    for row in raw[header_index + 1:]:
        if (_read_column(row, mapping, 'product_name_raw') or
                _read_column(row, mapping, 'amazon_name')):
            sample.append(row)
            if len(sample) == 100:
                break
    if len(sample) < 5:
        return {}, []
    used = set(mapping.values())
    inferred, ambiguity = {}, []
    max_columns = min(200, max([len(header)] + [len(row) for row in sample]))
    tests = (
        ('asin', lambda text: bool(ASIN.fullmatch(text.upper()))),
        ('source_profit_label', lambda text: bool(
            re.match(r'^(?:微黒字|黒字|赤字)(?=$|[\s(・/／:：])', text))),
    )
    for field, matches in tests:
        if field in mapping:
            continue
        candidates = []
        for col in range(max_columns):
            if col in used or (col < len(header) and _text(header[col])):
                continue
            values = [row[col] for row in sample if col < len(row)
                      and isinstance(row[col], str) and _text(row[col])]
            # A candidate must cover most product rows, not just a small
            # nonempty subsection. Formula-like strings cannot qualify.
            count = sum(bool(not value.lstrip().startswith('=') and matches(_text(value)))
                        for value in values)
            if (count >= 5 and count * 10 >= len(values) * 9
                    and count * 10 >= len(sample) * 8):
                candidates.append(col)
        if len(candidates) == 1:
            inferred[field] = candidates[0]
            used.add(candidates[0])
        elif len(candidates) > 1:
            ambiguity.append(field)
    return inferred, ambiguity


def _tax_mode(header):
    h = normalize_header(header)
    if '税込' in h:
        return 'included'
    if '税抜' in h:
        return 'excluded'
    return 'unknown'


def parse_rows(rows, *, document_type, source_file_id='', source_url='', source_sheet='',
               header_row=None, max_rows=20000, include_sensitive=False):
    """Parse a 2-D worksheet matrix into source-linked, redacted records.

    `header_row` is 1-based, or auto-select within the first 20 physical rows.
    include_sensitive=True exposes raw purchase prices and notes in the returned data;
    callers MUST keep the output in approved private storage, never GitHub.
    """
    if document_type not in DOCUMENT_TYPES:
        raise ValueError('document_type must be explicitly specified')
    if type(max_rows) is not int or not 1 <= max_rows <= 20000:
        raise ValueError('max_rows must be 1..20000')
    if header_row is not None and (type(header_row) is not int or header_row < 1):
        raise ValueError('header_row must be a positive integer')
    raw = []
    for i, row in enumerate(rows):
        if i > max_rows + 20:
            raise ValueError('input exceeds max_rows')
        raw.append(list(row))
    if not raw:
        raise ValueError('empty input')
    choices = [header_row - 1] if header_row is not None else range(min(20, len(raw)))
    best = None
    for i in choices:
        if i >= len(raw):
            raise ValueError('header row outside input')
        mapping, ambiguous = _mapping(raw[i], document_type)
        score = _header_score(mapping, document_type)
        if score > 0 and (best is None or (score, -i) > best[0]):
            best = ((score, -i), i, mapping, ambiguous)
    if best is None:
        raise ValueError('no reliable header: select document type or header_row')
    _, hidx, mapping, ambiguous = best
    inferred, inferred_ambiguous = _infer_unlabeled_columns(
        raw, hidx, mapping, document_type)
    mapping = {**mapping, **inferred}
    head = raw[hidx]
    records, warnings = [], []
    if inferred_ambiguous:
        warnings.append({'row': hidx + 1, 'codes': ['AMBIGUOUS_INFERRED_COLUMNS'],
                         'fields': inferred_ambiguous})
    if ambiguous:
        warnings.append({'row': hidx + 1, 'codes': ['AMBIGUOUS_COLUMNS'], 'fields': ambiguous})
    inherited_maker = ''
    inherited_terms = ''
    for physical_index, row in enumerate(raw[hidx + 1:], hidx + 2):
        if not any(_text(cell) for cell in row):
            inherited_maker = ''  # Do not inherit a company through a blank section.
            inherited_terms = ''
            continue
        maker = _read_column(row, mapping, 'manufacturer_name_raw')
        if maker:
            inherited_maker = maker
            inherited_terms = ''  # Terms must not leak across supplier groups.
        elif document_type not in ('manufacturer_list', 'price_revision'):
            maker = inherited_maker
        trade_terms = _read_column(row, mapping, 'trade_terms')
        if trade_terms:
            inherited_terms = trade_terms
        elif document_type not in ('manufacturer_list', 'price_revision'):
            trade_terms = inherited_terms
        product = _read_column(row, mapping, 'product_name_raw')
        amazon_product = _read_column(row, mapping, 'amazon_name')
        if document_type == 'manufacturer_list':
            if not maker:
                continue
        elif not (product or _read_column(row, mapping, 'jan_string') or amazon_product or
                  _read_column(row, mapping, 'asin')):
            # A section title with only a supplier name is not a product record.
            continue
        errors = []
        def idval(field, kind):
            i = mapping.get(field)
            value = row[i] if i is not None and i < len(row) else None
            result, error = _identifier(value, kind=kind)
            if error:
                errors.append(error)
            return result
        jan = idval('jan_string', 'JAN')
        asin_ix = mapping.get('asin')
        asin_value = row[asin_ix] if asin_ix is not None and asin_ix < len(row) else None
        asins, asin_errors = _asin_candidates(asin_value)
        errors.extend(asin_errors)
        if asins and 'asin' in inferred:
            errors.append('ASIN_UNLABELED_COLUMN_INFERRED')
        if not asins and 'asin' not in mapping:
            # For unnamed columns, accept one plausible *candidate* but never call it matched.
            candidates = []
            for i, cell in enumerate(row):
                if i in mapping.values() or not isinstance(cell, str):
                    continue
                t = _text(cell).upper()
                if t.startswith('B0') and ASIN.fullmatch(t):
                    candidates.append(t)
            if len(set(candidates)) == 1 and candidates:
                asins = [candidates[0]]
                errors.append('ASIN_UNLABELED_CANDIDATE')
        # A single-ASIN convenience field is deliberately blank for multi-ASIN rows.
        asin = asins[0] if len(asins) == 1 else ''
        note = _read_column(row, mapping, 'notes')
        risk_text = ' | '.join(_text(x)[:1000] for x in row if isinstance(x, str))
        if trade_terms:
            risk_text += ' | ' + trade_terms[:2000]
        risks = {key for key, regex in RISKS.items() if regex.search(risk_text)}
        if asins:
            risks.add('ASIN_UNVERIFIED')
        if len(asins) > 1:
            risks.add('MULTIPLE_ASIN_CANDIDATES')
        if not product and (amazon_product or asins):
            risks.add('SUPPLIER_PRODUCT_UNKNOWN')
        cost_i = mapping.get('cost_amount')
        cost_value = row[cost_i] if cost_i is not None and cost_i < len(row) else None
        cost = _amount(cost_value)
        tax = _tax_mode(head[cost_i]) if cost_i is not None else 'unknown'
        unit = _read_column(row, mapping, 'order_multiple')
        if document_type == 'quote_response':
            if cost is None:
                risks.add('COST_UNKNOWN')
            if not unit:
                risks.add('UNIT_UNKNOWN')
            if tax == 'unknown':
                risks.add('TAX_UNKNOWN')
        label = _read_column(row, mapping, 'source_profit_label')
        if label and 'source_profit_label' in inferred:
            errors.append('PROFIT_UNLABELED_COLUMN_INFERRED')
        if not label:
            # An unlabeled profit comment may be present; no automatic interpretation.
            unlabeled = [str(c) for i, c in enumerate(row) if i not in mapping.values()
                         and isinstance(c, str) and any(x in c for x in ('黒字', '赤字'))]
            if unlabeled:
                errors.append('UNLABELED_PROFIT_TEXT')
                label = unlabeled[0]
        profit = _profit_label(label)
        if profit == 'conditional_or_unclassified':
            risks.add('CONDITIONAL_PROFIT')
        if errors:
            warnings.append({'row': physical_index, 'codes': sorted(set(errors))})
        record = {
            'source_file_id': source_file_id,
            'source_url': source_url,
            'source_sheet': source_sheet,
            'source_row': physical_index,
            'document_type': document_type,
            'manufacturer_name_raw': maker,
            'manufacturer_code': _read_column(row, mapping, 'manufacturer_code'),
            'product_name_raw': product,
            'model_number': _read_column(row, mapping, 'model_number'),
            'jan_string': jan,
            'asin_candidate': asin,
            'asin_candidates': asins,
            'source_group': source_sheet,  # Sheet label is not proof of manufacturer identity.
            'trade_terms_present': bool(trade_terms),
            'order_multiple': unit,
            'cost_present': cost is not None,
            'cost_tax_mode': tax,
            'source_profit_status': profit,
            'risk_codes': sorted(risks),
            'decision': 'needs_confirmation',
        }
        if include_sensitive:
            record.update(cost_amount=cost, notes=note, trade_terms=trade_terms,
                          source_profit_label_raw=label, product_name_amazon=amazon_product)
        records.append(record)
    counts = Counter(code for rec in records for code in rec['risk_codes'])
    return {
        'schema_version': SCHEMA_VERSION,
        'document_type': document_type,
        'source_file_id': source_file_id,
        'source_url': source_url,
        'source_sheet': source_sheet,
        'header_row': hidx + 1,
        'mapped_columns': {key: i + 1 for key, i in mapping.items() if key not in inferred},
        'inferred_columns': {key: i + 1 for key, i in inferred.items()},
        'summary': {'record_count': len(records), 'risk_counts': dict(sorted(counts.items())),
                    'warning_count': len(warnings),
                    'inferred_fields': sorted(inferred)},
        'warnings': warnings,
        'records': records,
    }
