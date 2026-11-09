"""Offline Ed25519 review receipts without sharing reviewer signing secrets.

A trusted, independently authenticated reviewer can sign an exact Drive
revision on their OWN device. An inspection worker may verify the signature
using only a pinned public key. This avoids giving the worker a secret capable
of creating review approvals and needs no paid signing service.

No signer identity verification, key provisioning, protected persistence,
review UI, purchases, file writes or network actions are implemented here.
Never place a private key or real supplier data in a GitHub repository.
"""
from datetime import datetime, timezone
import hashlib
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)

from .review_gate import (
    _canonical, _pending_revisions, ACTOR_PATTERN,
    EVIDENCE_PATTERN, TIME_PATTERN, MAX_RECEIPTS,
)
from .snapshot_store import finalize_inventory

SCHEMA = 'supplier-ed25519-review-v1'
_SIG = re.compile(r'^[0-9a-f]{128}$')
_FIELDS = frozenset({
    'schema_version', 'folder_id', 'file_id', 'event', 'revision_digest',
    'reviewer_id', 'evidence_ref', 'reviewed_at_utc', 'signature',
})


def issue_offline_ed25519_receipt(
        previous, current, *, folder_id, file_id, event,
        reviewer_id, evidence_ref, private_key, reviewed_at=None):
    """Sign an existing changed/unavailable event on the REVIEWER side only.

    External authentication, source inspection and authorization must occur
    before this function is called. It never assumes the user inspected data.
    """
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError('trusted local Ed25519 private key object required')
    if (not isinstance(reviewer_id, str)
            or not ACTOR_PATTERN.fullmatch(reviewer_id)
            or not isinstance(evidence_ref, str)
            or not EVIDENCE_PATTERN.fullmatch(evidence_ref)):
        raise ValueError('trusted reviewer and evidence references required')
    pending, _ = _pending_revisions(previous, current)
    location = (folder_id, file_id, event)
    if location not in pending:
        raise ValueError('unchanged or unrecognized source version')
    when = reviewed_at if reviewed_at is not None else datetime.now(timezone.utc)
    if not isinstance(when, datetime) or when.tzinfo is None:
        raise ValueError('review timestamp must be timezone-aware')
    when = when.astimezone(timezone.utc).replace(microsecond=0)
    body = {
        'schema_version': SCHEMA,
        'folder_id': folder_id,
        'file_id': file_id,
        'event': event,
        'revision_digest': pending[location],
        'reviewer_id': reviewer_id,
        'evidence_ref': evidence_ref,
        'reviewed_at_utc': when.strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    return {**body, 'signature': private_key.sign(_canonical(body)).hex()}


def plan_offline_ed25519_retries(
        previous, current, *, receipts, trusted_public_keys):
    """Return private retry locations + public-safe counts.

    trusted_public_keys maps exact allowed reviewer IDs to Ed25519 public
    key objects, which the worker can have without a signing capability.
    Every unexpected, duplicate, tampered or stale receipt fails closed.
    """
    if (not isinstance(trusted_public_keys, dict)
            or not trusted_public_keys or
            any(not isinstance(who, str)
                or not ACTOR_PATTERN.fullmatch(who)
                or not isinstance(key, Ed25519PublicKey)
                for who, key in trusted_public_keys.items())):
        raise ValueError('explicit trusted Ed25519 public keys required')
    if not isinstance(receipts, (tuple, list)) or len(receipts) > MAX_RECEIPTS:
        raise ValueError('invalid receipt collection')
    pending, _ = _pending_revisions(previous, current)
    seen = set()
    for row in receipts:
        if not isinstance(row, dict) or frozenset(row) != _FIELDS:
            raise ValueError('invalid Ed25519 receipt fields')
        if any(not isinstance(v, str) for v in row.values()):
            raise ValueError('review receipt fields must be strings')
        reviewer = row['reviewer_id']
        if (row['schema_version'] != SCHEMA
                or reviewer not in trusted_public_keys
                or not EVIDENCE_PATTERN.fullmatch(row['evidence_ref'])):
            raise ValueError('unknown reviewer, receipt or evidence reference')
        when = row['reviewed_at_utc']
        if not TIME_PATTERN.fullmatch(when):
            raise ValueError('invalid UTC timestamp')
        try:
            datetime.strptime(when, '%Y-%m-%dT%H:%M:%SZ')
        except ValueError:
            raise ValueError('invalid UTC timestamp') from None
        loc = (row['folder_id'], row['file_id'], row['event'])
        if (loc not in pending or row['revision_digest'] != pending[loc]
                or loc in seen):
            raise ValueError('duplicate, unknown or stale reviewed revision')
        if not _SIG.fullmatch(row['signature']):
            raise ValueError('invalid Ed25519 signature encoding')
        unsigned = {field: value for field, value in row.items()
                    if field != 'signature'}
        try:
            trusted_public_keys[reviewer].verify(
                bytes.fromhex(row['signature']), _canonical(unsigned))
        except InvalidSignature:
            raise ValueError('untrusted or tampered Ed25519 receipt') from None
        seen.add(loc)
    outstanding = sorted(set(pending) - seen)
    to_retry = [(folder_id, file_id) for folder_id, file_id, event in outstanding
                if event == 'changed']
    unavailable = [(folder_id, file_id) for folder_id, file_id, event in outstanding
                   if event == 'unavailable']
    return {
        'private_retry_locations': to_retry,
        'private_unavailable_locations': unavailable,
        'private_verified_locations': sorted(seen),
        'summary': {
            'total_changes_needing_review': len(pending),
            'verified_receipts': len(seen),
            'retry_pending': len(to_retry),
            'access_review_pending': len(unavailable),
            'ready_to_finalize': not outstanding,
            'baseline_advanced': False,
            'review_worker_has_signing_capability': False,
            'additional_signing_service_required': False,
        },
    }


def finalize_with_offline_ed25519_receipts(
        previous, current, *, receipts, trusted_public_keys):
    """Return an approved baseline object; never write data or start work."""
    plan = plan_offline_ed25519_retries(
        previous, current, receipts=receipts,
        trusted_public_keys=trusted_public_keys)
    if not plan['summary']['ready_to_finalize']:
        raise ValueError('unreviewed source changes remain')
    checked = plan['private_verified_locations']
    return finalize_inventory(
        previous, current,
        completed_locations=[(folder, file_id) for folder, file_id, event in checked
                             if event == 'changed'],
        reviewed_unavailable=[(folder, file_id) for folder, file_id, event in checked
                              if event == 'unavailable'],
    )
