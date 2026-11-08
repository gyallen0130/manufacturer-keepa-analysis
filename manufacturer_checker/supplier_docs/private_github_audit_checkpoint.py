"""Private GitHub transport for a SINGLE encrypted inventory + review audit.

No provisioning, source access, key creation, signing, scheduling or automatic
approval. Uses an injected authenticated session; by default tests use a fake.
The repository MUST be privately owned and verified independently. GitHub
history retains old ciphertext; protect the Fernet key separately.

This adapter is intentionally NOT connected to production SP-API code or any
GitHub Actions workflow.
"""
import base64
import json

from cryptography.fernet import InvalidToken

from .review_gate import _canonical
from .snapshot_store import _cipher, MAX_CIPHERTEXT_BYTES
from .private_github_state import (
    PrivateGithubCheckpoint, AUDIT_PATH, SHA, BRANCH,
)
from .private_audit_bundle import (
    MAX_PLAINTEXT_BYTES, initialize_audit_bundle,
    verify_audit_bundle, propose_next_audit_bundle,
)


class PrivateGithubAuditCheckpoint:
    def __init__(self, session, *, repository):
        self._transport = PrivateGithubCheckpoint(
            session, repository=repository, object_path=AUDIT_PATH)

    def _read_cipher(self, *, key, trusted_public_keys):
        self._transport._validate_target()
        cipher, sha = self._transport._fetch_content()
        if cipher is None:
            raise FileNotFoundError('private audit checkpoint not initialized')
        try:
            plaintext = _cipher(key).decrypt(cipher)
            if len(plaintext) > MAX_PLAINTEXT_BYTES:
                raise ValueError('audit checkpoint size limit exceeded')
            bundle = json.loads(plaintext)
        except (InvalidToken, UnicodeError, json.JSONDecodeError):
            raise ValueError('private encrypted audit checkpoint invalid') from None
        verified = verify_audit_bundle(
            bundle, trusted_public_keys=trusted_public_keys)
        return bundle, verified['summary'], sha

    def read(self, *, key, trusted_public_keys):
        """Read and replay every signed transition, never silently trust JSON."""
        bundle, summary, sha = self._read_cipher(
            key=key, trusted_public_keys=trusted_public_keys)
        return {'private_bundle': bundle, 'summary': summary, 'blob_sha': sha}

    def _write_cipher(self, *, bundle, key, expected_sha):
        if expected_sha is not None and (
                not isinstance(expected_sha, str) or
                not SHA.fullmatch(expected_sha)):
            raise ValueError('expected private blob SHA must be complete')
        data = _canonical(bundle)
        if len(data) > MAX_PLAINTEXT_BYTES:
            raise ValueError('private audit bundle is oversized')
        encrypted = _cipher(key).encrypt(data)
        if len(encrypted) > MAX_CIPHERTEXT_BYTES:
            raise ValueError('private encrypted audit bundle is oversized')
        payload = {
            'message': 'Update encrypted supplier audit checkpoint',
            'content': base64.b64encode(encrypted).decode('ascii'),
            'branch': BRANCH,
        }
        if expected_sha:
            payload['sha'] = expected_sha
        return self._transport._put(payload)

    def initialize(self, *, key, first_snapshot, trusted_public_keys,
                   approve_initial_baseline=False):
        """Explicit one-time initialization; never backfills old source data."""
        bundle = initialize_audit_bundle(
            first_snapshot,
            approve_initial_baseline=approve_initial_baseline)
        verify_audit_bundle(bundle, trusted_public_keys=trusted_public_keys)
        self._transport._validate_target()
        current, _ = self._transport._fetch_content()
        if current is not None:
            raise FileExistsError('private audit checkpoint already exists')
        return self._write_cipher(bundle=bundle, key=key, expected_sha=None)

    def advance_after_review(self, *, key, expected_sha, current_snapshot,
                             receipts, trusted_public_keys):
        """Write ONE complete inventory+audit blob with GitHub SHA protection.

        Caller must separately verify REAL Drive revisions just before commit,
        protect private repository branches/workflows and authenticate reviewer
        identities. A failed GitHub response is NOT automatic success/retry.
        """
        if not isinstance(expected_sha, str) or not SHA.fullmatch(expected_sha):
            raise ValueError('expected private blob SHA is required')
        current = self.read(key=key, trusted_public_keys=trusted_public_keys)
        if current['blob_sha'] != expected_sha:
            raise ValueError('stale private GitHub audit checkpoint')
        proposed = propose_next_audit_bundle(
            current['private_bundle'], current_snapshot,
            receipts=receipts, trusted_public_keys=trusted_public_keys)
        if proposed == current['private_bundle']:
            return {'written': False, 'unchanged': True}
        new_sha = self._write_cipher(
            bundle=proposed, key=key, expected_sha=expected_sha)
        return {'written': True, 'new_blob_sha': new_sha}
