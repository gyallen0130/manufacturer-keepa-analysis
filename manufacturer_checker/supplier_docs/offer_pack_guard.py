"""Offline fail-closed guard for supplier quote unit vs Amazon offer bundle.

The manufacturer's barcode can describe ONE retail box while an Amazon ASIN
may represent a multi-box offer. A supplier "case quantity" is wholesale
logistics, NOT evidence that the quote is one retail box or an Amazon offer.
No price/profit calculation, external I/O, source edits, or SKU confirmation.
"""
from collections.abc import Mapping

_MAX_COUNT = 10000
_ALLOWED = frozenset({
    'amazon_direct_verified', 'secondary_listing', 'unverified',
})


def _count(container, key):
    value = container.get(key)
    if value is None:
        return None
    if type(value) is not int or not 1 <= value <= _MAX_COUNT:
        raise ValueError('invalid or excessive package count')
    return value


def mark_records_from_pack_guard(records, guard):
    """Propagate unresolved pack identity into offline identity comparisons.

    Never fills in missing product counts, changes original records or claims
    a retailer mirror is the direct Amazon listing. No SKU or cost values
    leave the process; caller chooses only the authorized input rows.
    """
    if (not isinstance(records, (list, tuple)) or len(records) > 200
            or not all(isinstance(rec, dict) for rec in records)
            or not isinstance(guard, Mapping)
            or not isinstance(guard.get('public_summary'), Mapping)):
        raise ValueError('invalid supplier pack review inputs')
    status = guard['public_summary'].get('status')
    allowed_statuses = frozenset({
        'needs_amazon_offer_unit', 'needs_quoted_purchase_unit',
        'confirmed_count_mismatch', 'potential_count_mismatch_secondary',
        'apparent_count_match_secondary_unverified',
        'count_match_identity_still_unverified',
    })
    if status not in allowed_statuses:
        raise ValueError('unrecognized supplier pack review status')
    needs_review = status != 'count_match_identity_still_unverified'
    return [
        {**row, 'offer_pack_review_required': True}
        if needs_review else dict(row)
        for row in records
    ]


def evaluate_offer_pack_guard(quote, listing):
    """Return private non-identifier evidence and a log-safe decision.

    quote:
      items_per_inner_box: known manufacturer retail-box item count (optional)
      inner_boxes_per_quoted_unit: count specifically stated for ONE quote unit
      quote_unit_verified: explicit confirmation of quoted purchase unit
      case_pack: warehouse/carton count; intentionally NEVER used.

    listing:
      items_per_inner_box: number of items in each box of the ASIN offer
      inner_boxes_per_offer: boxes in ONE ASIN offer
      source: amazon_direct_verified | secondary_listing | unverified

    Every count is *explicit input*, never inferred from a JAN/ASIN or
    supplier case pack. The function does NOT establish product identity.
    """
    if not isinstance(quote, Mapping) or not isinstance(listing, Mapping):
        raise ValueError('quote and listing must be mappings')
    q_items = _count(quote, 'items_per_inner_box')
    q_boxes = _count(quote, 'inner_boxes_per_quoted_unit')
    _count(quote, 'case_pack')  # Validate only. Never equate to retail offer.
    l_items = _count(listing, 'items_per_inner_box')
    l_boxes = _count(listing, 'inner_boxes_per_offer')
    q_verified = quote.get('quote_unit_verified', False)
    if type(q_verified) is not bool:
        raise ValueError('invalid quote verification flag')
    source = listing.get('source', 'unverified')
    if source not in _ALLOWED:
        raise ValueError('invalid listing evidence level')

    expected = q_items * q_boxes if q_items and q_boxes else None
    observed = l_items * l_boxes if l_items and l_boxes else None

    if observed is None:
        status = 'needs_amazon_offer_unit'
    elif expected is None or not q_verified:
        status = 'needs_quoted_purchase_unit'
    elif expected != observed:
        status = ('confirmed_count_mismatch'
                  if source == 'amazon_direct_verified'
                  else 'potential_count_mismatch_secondary')
    elif source != 'amazon_direct_verified':
        status = 'apparent_count_match_secondary_unverified'
    else:
        status = 'count_match_identity_still_unverified'

    # A known supplier box and a multi-box secondary listing is still an
    # important manual warning, even when the quote unit has not been proved.
    multipack_hint = bool(q_items and l_items and q_items == l_items
                          and l_boxes and l_boxes > 1)
    return {
        'public_summary': {
            'status': status,
            'listing_source': source,
            'multipack_hint': multipack_hint,
            'quote_unit_confirmed': q_verified,
            'amazon_product_identity_confirmed': False,
            'profit_calculation_allowed': False,
            'purchase_allowed': False,
            'source_writes': 0,
            'api_calls': 0,
        },
        # Non-price counts. Keep with authorized supplier context, not in CI
        # logs or public GitHub item-by-item records.
        'private_counts': {
            'quoted_total_items': expected,
            'listed_total_items': observed,
            'quoted_inner_boxes': q_boxes,
            'listed_inner_boxes': l_boxes,
        },
    }
