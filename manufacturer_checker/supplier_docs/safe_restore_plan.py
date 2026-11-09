"""Fail-closed OFFLINE recovery gate for an encrypted supplier audit backup.

This consumes caller-supplied evidence from a SEPARATE, independently
authenticated remote read. It DOES NOT fetch GitHub, inspect Drive, authenticate
humans, make files, restore a branch, or grant any approval. A snapshot of a
matching GitHub blob is necessary but NOT sufficient for safe production restore:
the caller must separately ensure no concurrent update after its observation.

IMPORTANT: operator flags are assertions, not cryptographic proofs. They are
never recorded as confirmation of actual Google Drive or GitHub state.
"""
import hmac

from .offline_recovery_archive import (
    _github_blob_sha, inspect_offline_recovery_archive,
    prepare_offline_recovery_ciphertext,
)
from .private_github_state import SHA


_REQUIRED_CHECKS = (
    'private_repository_ownership_confirmed',
    'separate_backup_location_confirmed',
    'recovery_key_stored_separately',
    'trusted_reviewer_registry_confirmed',
    'drive_source_revisions_checked',
    'owner_approved_manual_recovery',
)


def assess_manual_restore(
        archive, *, recovery_key, trusted_public_keys,
        observed_remote_ciphertext=None, observed_remote_blob_sha=None,
        private_repository_ownership_confirmed=False,
        separate_backup_location_confirmed=False,
        recovery_key_stored_separately=False,
        trusted_reviewer_registry_confirmed=False,
        drive_source_revisions_checked=False,
        owner_approved_manual_recovery=False):
    """Return only redacted findings; NEVER approve or write to GitHub.

    A deleted/unavailable remote or one more recent than the archive stops.
    Even when equal, the operator must re-check the remote generation again
    if there is a later separate PUT, and use an expected blob SHA condition.
    """
    private = inspect_offline_recovery_archive(
        archive, recovery_key=recovery_key,
        trusted_public_keys=trusted_public_keys)
    source_sha = private['private_source_blob_sha']
    checks = {
        key: value for key, value in locals().items()
        if key in _REQUIRED_CHECKS
    }
    if any(type(value) is not bool for value in checks.values()):
        raise ValueError('manual recovery assertions must be booleans')
    if observed_remote_ciphertext is None and observed_remote_blob_sha is None:
        action = 'halt_remote_state_unavailable'
        same = False
    else:
        if (not isinstance(observed_remote_ciphertext, bytes)
                or not isinstance(observed_remote_blob_sha, str)
                or not SHA.fullmatch(observed_remote_blob_sha)
                or not hmac.compare_digest(
                    _github_blob_sha(observed_remote_ciphertext),
                    observed_remote_blob_sha)):
            raise ValueError('supplied remote ciphertext and SHA do not match')
        same = hmac.compare_digest(source_sha, observed_remote_blob_sha)
        if not same:
            action = 'halt_backup_stale_or_remote_changed'
        elif not all(checks.values()):
            action = 'halt_manual_custody_and_source_checks_incomplete'
        else:
            action = 'local_reencryption_preparation_only'
    return {
        'action': action,
        'summary': {
            'backup_signatures_reverified': True,
            'review_cycles_reverified': private['summary']['review_cycles_verified'],
            'remote_matches_backup_source': same,
            'manual_checks_complete_as_declared': all(checks.values()),
            'operator_assertions_independently_verified': False,
            'remote_snapshot_recheck_needed_before_any_upload': True,
            'github_or_drive_calls': 0,
            'files_or_secrets_written': False,
            'restoration_committed': False,
        },
    }


def prepare_manually_checked_recovery(
        archive, *, recovery_key, new_primary_key,
        trusted_public_keys, observed_remote_ciphertext,
        observed_remote_blob_sha, **manual_checks):
    """Return NEW encrypted bytes only if remote matches and checks declared.

    Not a GitHub write API. After this, a trusted human must independently
    re-fetch the remote, compare against the same blob SHA and review current
    Drive versions; only a separate guarded write path can save it.
    """
    result = assess_manual_restore(
        archive, recovery_key=recovery_key,
        trusted_public_keys=trusted_public_keys,
        observed_remote_ciphertext=observed_remote_ciphertext,
        observed_remote_blob_sha=observed_remote_blob_sha,
        **manual_checks)
    if result['action'] != 'local_reencryption_preparation_only':
        raise ValueError('offline recovery preconditions not met')
    prepared = prepare_offline_recovery_ciphertext(
        archive, recovery_key=recovery_key,
        new_primary_key=new_primary_key,
        trusted_public_keys=trusted_public_keys,
        approve_offline_recovery=True)
    if not hmac.compare_digest(
            prepared['private_source_blob_sha'], observed_remote_blob_sha):
        raise ValueError('offline source revision changed during preparation')
    return {
        'private_reencrypted_checkpoint': prepared['private_reencrypted_checkpoint'],
        'summary': {
            **result['summary'],
            'new_ciphertext_prepared': True,
            'remote_write_performed': False,
        },
    }
