"""Authenticated review receipts and deterministic retry planning (development only).

Pure functions: no API calls, no writes, no scheduling or automatic purchasing.
A receipt proves possession of a dedicated HMAC signing key, NOT independent
proof of a human's identity. Only an authenticated review application should
hold that key and issue receipts after an actual completed review.
Receipts, file IDs and revision hashes are private operational data.
"""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re

from .drive_delta import plan_explicit_folder_set
from .snapshot_store import finalize_inventory

RECEIPT_SCHEMA = 'supplier-review-receipt-v1'
ACTOR_PATTERN = re.compile(r'^[A-Za-z0-9_.-]{3,100}$')
EVIDENCE_PATTERN = re.compile(r'^[A-Za-z0-9_-]{8,128}$')
TIME_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
MAX_RECEIPTS = 10000


def _key(signing_key):
    if not isinstance(signing_key, bytes) or len(signing_key) < 32:
        raise ValueError('a dedicated 32-byte or longer signing key is required')
    return signing_key


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _pending_revisions(previous, current):
    if previous is None:
        raise ValueError('initial inventory requires separate baseline approval')
    plan = plan_explicit_folder_set(previous, current)
    pending = {}
    for folder_id, file_id in plan['candidate_locations']:
        meta = current[folder_id]['files'][file_id]
        value = ['changed', folder_id, file_id, meta]
        pending[(folder_id, file_id, 'changed')] = hashlib.sha256(
            _canonical(value)).hexdigest()
    for folder_id, file_id in plan['unavailable_locations']:
        meta = previous[folder_id]['files'][file_id]
        value = ['unavailable', folder_id, file_id, meta]
        pending[(folder_id, file_id, 'unavailable')] = hashlib.sha256(
            _canonical(value)).hexdigest()
    return pending, plan


def issue_review_receipt(previous, current, *, folder_id, file_id, event,
                         reviewer_id, evidence_ref, signing_key, reviewed_at=None):
    """Issue only from an externally authenticated, authorized review process.

    Never call this directly from a parser, scheduler or Drive inventory job.
    'changed' means explicit review of this revision, not purchase approval.
    'unavailable' means access was manually checked, NOT deletion.
    """
    key = _key(signing_key)
    if not isinstance(reviewer_id, str) or not ACTOR_PATTERN.fullmatch(reviewer_id):
        raise ValueError('invalid reviewer reference')
    if not isinstance(evidence_ref, str) or not EVIDENCE_PATTERN.fullmatch(evidence_ref):
        raise ValueError('invalid private evidence reference')
    pending, _ = _pending_revisions(previous, current)
    location = (folder_id, file_id, event)
    if location not in pending:
        raise ValueError('unapproved or unchanged receipt target')
    when = reviewed_at or datetime.now(timezone.utc)
    if not isinstance(when, datetime) or when.tzinfo is None:
        raise ValueError('review time must be timezone aware')
    stamp = when.astimezone(timezone.utc).replace(microsecond=0).strftime(
        '%Y-%m-%dT%H:%M:%SZ')
    body = {
        'schema_version': RECEIPT_SCHEMA,
        'folder_id': folder_id,
        'file_id': file_id,
        'event': event,
        'revision_digest': pending[location],
        'reviewer_id': reviewer_id,
        'evidence_ref': evidence_ref,
        'reviewed_at_utc': stamp,
    }
    return {**body, 'signature': hmac.new(key, _canonical(body),
                                         hashlib.sha256).hexdigest()}


def plan_review_retries(previous, current, *, receipts, signing_key,
                        allowed_reviewers):
    """Validate signed, revision-pinned receipts; return an inert retry plan.

    Unexpected, forged, duplicated and stale receipts all raise, instead of
    being silently ignored. Never return private identifiers in summary.
    """
    key = _key(signing_key)
    if (not isinstance(allowed_reviewers, (set, frozenset))
            or not allowed_reviewers
            or any(not isinstance(actor, str) or
                   not ACTOR_PATTERN.fullmatch(actor)
                   for actor in allowed_reviewers)):
        raise ValueError('explicit trusted reviewer allowlist required')
    if (not isinstance(receipts, (list, tuple))
            or len(receipts) > MAX_RECEIPTS):
        raise ValueError('invalid review receipt collection')
    pending, plan = _pending_revisions(previous, current)
    seen = set()
    approved = set()
    fields = {
        'schema_version', 'folder_id', 'file_id', 'event', 'revision_digest',
        'reviewer_id', 'evidence_ref', 'reviewed_at_utc', 'signature'}
    for record in receipts:
        if not isinstance(record, dict) or set(record) != fields:
            raise ValueError('invalid review receipt format')
        if record['schema_version'] != RECEIPT_SCHEMA:
            raise ValueError('unsupported review receipt version')
        if (record['reviewer_id'] not in allowed_reviewers
                or not ACTOR_PATTERN.fullmatch(record['reviewer_id'])
                or not isinstance(record['evidence_ref'], str)
                or not EVIDENCE_PATTERN.fullmatch(record['evidence_ref'])):
            raise ValueError('reviewer or evidence reference not approved')
        stamp = record['reviewed_at_utc']
        if not isinstance(stamp, str) or not TIME_PATTERN.fullmatch(stamp):
            raise ValueError('invalid review timestamp')
        try:
            datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ')
        except ValueError:
            raise ValueError('invalid review timestamp') from None
        loc = (record['folder_id'], record['file_id'], record['event'])
        if loc not in pending or pending[loc] != record['revision_digest']:
            raise ValueError('unrecognized or stale review receipt')
        if loc in seen:
            raise ValueError('duplicate review receipt')
        seen.add(loc)
        sig = record['signature']
        if not isinstance(sig, str) or not re.fullmatch(r'[0-9a-f]{64}', sig):
            raise ValueError('invalid review signature format')
        unsigned = {k: v for k, v in record.items() if k != 'signature'}
        expected_sig = hmac.new(key, _canonical(unsigned),
                                hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            raise ValueError('review signature verification failed')
        approved.add(loc)
    outstanding = sorted(set(pending) - approved)
    to_retry = [(folder, file_id) for folder, file_id, event in outstanding
                if event == 'changed']
    need_access_review = [(folder, file_id) for folder, file_id, event in outstanding
                          if event == 'unavailable']
    return {
        'private_retry_locations': to_retry,
        'private_unavailable_locations': need_access_review,
        'private_verified_locations': sorted(approved),
        'summary': {
            'total_changes_needing_review': len(pending),
            'verified_receipts': len(approved),
            'retry_pending': len(to_retry),
            'access_review_pending': len(need_access_review),
            'ready_to_finalize': not outstanding,
            'baseline_advanced': False,
        },
    }


def finalize_with_verified_receipts(previous, current, *, receipts, signing_key,
                                    allowed_reviewers):
    """Authorize advancing a private snapshot, without writing it.

    An external trusted reviewer must create valid, authenticated receipts.
    Callers must separately ensure source revisions have not changed again and
    persist the finalized snapshot with the version check in snapshot_store.
    """
    plan = plan_review_retries(
        previous, current, receipts=receipts, signing_key=signing_key,
        allowed_reviewers=allowed_reviewers)
    if not plan['summary']['ready_to_finalize']:
        raise ValueError('unreviewed files remain; baseline unchanged')
    verified = plan['private_verified_locations']
    return finalize_inventory(
        previous, current,
        completed_locations=[(f, doc) for f, doc, event in verified
                             if event == 'changed'],
        reviewed_unavailable=[(f, doc) for f, doc, event in verified
                              if event == 'unavailable'],
    )
