"""Private, encrypted-audit-bundle payload for a no-new-paid-storage pilot.

Pure data checks only: never creates accounts, calls GitHub, reaches Google
Drive, authenticates a reviewer, or modifies a source. The owner must explicitly
approve first-baseline semantics and separately verify the reviewer identities.

To avoid a crash between two independent state writes, the *current baseline*
and its encrypted review history form ONE payload, written with ONE GitHub
Contents blob-SHA precondition by the private-only transport.

Records contain sensitive IDs and reviewer evidence. NEVER print/commit
plaintext or run against a public repository. The Ed25519 PRIVATE signing key
is never required by this module; use trusted pinned PUBLIC keys to verify.
"""
import hashlib
import json

from .review_gate import _canonical
from .snapshot_store import _validated_set
from .offline_review import finalize_with_offline_ed25519_receipts

SCHEMA = 'supplier-private-audit-bundle-v1'
MAX_HISTORY = 64
MAX_RECEIPTS_PER_CYCLE = 1000
MAX_PLAINTEXT_BYTES = 4_500_000


def _digest(snapshot):
    return hashlib.sha256(_canonical(snapshot)).hexdigest()


def _check_size(bundle):
    if len(_canonical(bundle)) > MAX_PLAINTEXT_BYTES:
        raise ValueError('private audit bundle size limit exceeded')


def initialize_audit_bundle(first_snapshot, *,
                            approve_initial_baseline=False):
    """Create an inert baseline after explicit acceptance of no backfill."""
    if approve_initial_baseline is not True:
        raise ValueError('explicit initial baseline acknowledgement required')
    _validated_set(first_snapshot)
    bundle = {
        'schema_version': SCHEMA,
        'initial_snapshot': first_snapshot,
        'current_snapshot': first_snapshot,
        'history': [],
    }
    _check_size(bundle)
    return bundle


def verify_audit_bundle(bundle, *, trusted_public_keys):
    """Replay EVERY historic signed transition before trusting latest state.

    Never infer reviewer authentication or a source's current Drive version
    from a valid signature alone. The key mapping must be managed separately.
    """
    if not isinstance(bundle, dict) or set(bundle) != {
        'schema_version', 'initial_snapshot', 'current_snapshot', 'history'
    } or bundle['schema_version'] != SCHEMA:
        raise ValueError('unrecognized private audit bundle')
    if (not isinstance(bundle['history'], list)
            or len(bundle['history']) > MAX_HISTORY):
        raise ValueError('invalid or oversized audit history')
    if not isinstance(trusted_public_keys, dict) or not trusted_public_keys:
        raise ValueError('trusted reviewer public keys required')
    _check_size(bundle)
    previous = bundle['initial_snapshot']
    _validated_set(previous)
    for index, item in enumerate(bundle['history'], start=1):
        if not isinstance(item, dict) or set(item) != {
            'sequence', 'previous_digest', 'current_digest',
            'current_snapshot', 'receipts',
        } or type(item['sequence']) is not int or item['sequence'] != index:
            raise ValueError('private audit sequence is inconsistent')
        current = item['current_snapshot']
        _validated_set(current)
        if (item['previous_digest'] != _digest(previous)
                or item['current_digest'] != _digest(current)
                or previous == current
                or not isinstance(item['receipts'], list)
                or not 1 <= len(item['receipts']) <= MAX_RECEIPTS_PER_CYCLE):
            raise ValueError('private audit chain is incomplete')
        approved = finalize_with_offline_ed25519_receipts(
            previous, current, receipts=item['receipts'],
            trusted_public_keys=trusted_public_keys)
        if approved != current:
            raise ValueError('audit approval did not match the checkpoint')
        previous = current
    _validated_set(bundle['current_snapshot'])
    if previous != bundle['current_snapshot']:
        raise ValueError('private audit final state does not match history')
    return {
        'private_current_snapshot': previous,
        'summary': {
            'historical_review_cycles': len(bundle['history']),
            'audit_replay_valid': True,
            'baseline_written': False,
            'cloud_or_github_api_calls': 0,
        },
    }


def propose_next_audit_bundle(bundle, current_snapshot, *, receipts,
                              trusted_public_keys):
    """Compute proposed single-object update; never write it automatically.

    Incomplete reviews, an unavailable item without review, changed revision
    or invalid signature reject the entire transition. Caller must re-scan
    Drive revisions and use a fresh GitHub blob SHA before any actual PUT.
    """
    old = verify_audit_bundle(
        bundle, trusted_public_keys=trusted_public_keys
    )['private_current_snapshot']
    _validated_set(current_snapshot)
    if current_snapshot == old:
        if receipts:
            raise ValueError('unchanged checkpoint must not accept receipts')
        return bundle
    if len(bundle['history']) >= MAX_HISTORY:
        raise ValueError('audit history requires separately approved archive')
    if not isinstance(receipts, list) or not 1 <= len(receipts) <= MAX_RECEIPTS_PER_CYCLE:
        raise ValueError('invalid review receipt batch')
    approved = finalize_with_offline_ed25519_receipts(
        old, current_snapshot, receipts=receipts,
        trusted_public_keys=trusted_public_keys)
    if approved != current_snapshot:
        raise ValueError('unreviewed changes cannot advance checkpoint')
    record = {
        'sequence': len(bundle['history']) + 1,
        'previous_digest': _digest(old),
        'current_digest': _digest(approved),
        'current_snapshot': approved,
        'receipts': list(receipts),
    }
    result = {
        'schema_version': SCHEMA,
        'initial_snapshot': bundle['initial_snapshot'],
        'current_snapshot': approved,
        'history': bundle['history'] + [record],
    }
    _check_size(result)
    return result
