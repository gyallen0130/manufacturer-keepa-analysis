"""Pure crash-recovery assessment for a future supplier-docs Cloud Run Job.

This module does not run Drive/Sheets APIs, decrypt objects, issue review
receipts, mutate inventory, schedule runs, or automatically approve documents.
It evaluates a *private* proposed scan against the *persisted* inventory.

A two-object inventory/journal system cannot commit atomically. If inventory
advanced but the journal has not been reconciled, HALT for manual review rather
than silently dropping review evidence or overwriting the old journal.
"""
from .review_gate import plan_review_retries
from .snapshot_store import _validated_set

RECOVERY_SCHEMA = 'supplier-recovery-check-v1'


def assess_recovery(previous, proposed, persisted, *, receipts,
                    signing_key, allowed_reviewers,
                    expected_generation, observed_generation):
    """Return a redacted, inert assessment of the next safe action.

    previous: private baseline captured at start of the review cycle.
    proposed: private complete approved-folder inventory from that cycle.
    persisted: inventory independently re-read from the private state store.
    expected_generation: persisted inventory generation from cycle start.
    observed_generation: persisted inventory generation just re-read now.

    Neither a successful plan nor an acknowledged review is permission to
    write. A trusted orchestrator must revalidate source revisions, ensure
    one-writer execution and separately issue a generation-guarded write.
    """
    for snapshot in (previous, proposed, persisted):
        _validated_set(snapshot)
    if (type(expected_generation) is not int or expected_generation < 1
            or type(observed_generation) is not int or observed_generation < 1):
        raise ValueError('positive persisted generations are mandatory')
    # Always validate receipts against the EXACT source versions before
    # deciding whether anything can safely advance. Forged/stale aborts.
    review = plan_review_retries(
        previous, proposed, receipts=receipts, signing_key=signing_key,
        allowed_reviewers=allowed_reviewers)
    pending = review['summary']
    changed_count = pending['total_changes_needing_review']
    if persisted == proposed and persisted != previous:
        action = 'halt_advanced_inventory_requires_journal_reconciliation'
    elif persisted != previous:
        action = 'halt_unexpected_persisted_inventory'
    elif expected_generation != observed_generation:
        action = 'halt_concurrent_inventory_generation'
    elif proposed == previous:
        action = 'no_changes_no_commit'
    elif pending['ready_to_finalize']:
        action = 'ready_for_external_revalidation_not_committed'
    else:
        action = 'resume_only_unreviewed_items'
    return {
        'schema_version': RECOVERY_SCHEMA,
        'action': action,
        'summary': {
            'review_items': changed_count,
            'reviewed': pending['verified_receipts'],
            'retry_pending': pending['retry_pending'],
            'access_review_pending': pending['access_review_pending'],
            'generation_matches_start': expected_generation == observed_generation,
            'baseline_advanced_by_this_check': False,
            'external_review_required': True,
            'cloud_api_calls': 0,
        },
    }
