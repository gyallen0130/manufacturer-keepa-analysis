"""Private GitHub Contents API checkpoint adapter (opt-in; NOT deployed).

Stores ONLY a Fernet-encrypted approved inventory in a PRIVATE repository
on a dedicated state-only branch. The calling process supplies an authenticated
HTTP session and key, neither of which are obtained or logged here.

Do NOT use a public repo, public GitHub Actions artifacts, unencrypted git
commits, or automatic changes triggered by untrusted pull requests.

GitHub's Contents API accepts an existing blob SHA on updates. Conflict or
unexpected responses must stop, not retry blindly. Git history keeps old
ciphertexts; losing the Fernet key makes old records irrecoverable.
"""
import base64
import json
import re

from cryptography.fernet import InvalidToken

from .offline_review import finalize_with_offline_ed25519_receipts
from .snapshot_store import (
    MAX_CIPHERTEXT_BYTES, _cipher, _validated_set, finalize_inventory,
)

OWNER_REPO = re.compile(r'^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$')
SHA = re.compile(r'^[a-f0-9]{40}$')
BRANCH = 'supplier-monitor-state'
PATH = 'private-state/supplier-docs-inventory.enc'
API = 'https://api.github.com'
HEADERS = {
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
}


class PrivateGithubCheckpoint:
    """No network on construction; live HTTP only on explicit method call.

    The injected session must already have scoped GitHub credentials. The
    GITHUB_TOKEN is repo-wide (not path-limited): use a dedicated PRIVATE
    repository, protected workflow code and an isolated state branch.
    """

    def __init__(self, session, *, repository):
        if (not isinstance(repository, str) or
                not OWNER_REPO.fullmatch(repository) or
                any(s in ('.', '..') for s in repository.split('/'))):
            raise ValueError('explicit private repository is required')
        if (not callable(getattr(session, 'get', None)) or
                not callable(getattr(session, 'put', None))):
            raise ValueError('an authenticated HTTP session is required')
        self._session = session
        self._base = API + '/repos/' + repository
        self._file = self._base + '/contents/' + PATH

    def _get(self, url, *, params=None):
        try:
            response = self._session.get(
                url, headers=HEADERS, params=params,
                timeout=20, allow_redirects=False)
            status = response.status_code
            if status in (200, 404):
                return status, response.json() if status == 200 else None
        except Exception:
            raise RuntimeError('private checkpoint read failed') from None
        raise RuntimeError('private checkpoint API refused read') from None

    def _put(self, payload):
        try:
            response = self._session.put(
                self._file, headers=HEADERS, json=payload, timeout=20,
                allow_redirects=False)
            if response.status_code in (200, 201):
                data = response.json()
                sha = data.get('content', {}).get('sha')
                if isinstance(sha, str) and SHA.fullmatch(sha):
                    return sha
        except Exception:
            raise RuntimeError('private checkpoint write failed') from None
        raise RuntimeError('checkpoint write was not confirmed; manual review needed') from None

    def _validate_target(self):
        status, repo = self._get(self._base)
        if (status != 200 or not isinstance(repo, dict)
                or repo.get('private') is not True
                or repo.get('archived') is not False
                or repo.get('full_name', '').lower() !=
                self._base.rsplit('/repos/', 1)[-1].lower()):
            raise PermissionError('checkpoint target is not verified private and active')
        status, branch = self._get(self._base + '/branches/' + BRANCH)
        if (status != 200 or not isinstance(branch, dict)
                or branch.get('name') != BRANCH):
            raise PermissionError('dedicated state branch not verified')
        # Branch settings and actual repository rulesets must still be reviewed
        # externally. We neither create nor bypass branch protection.

    def _fetch_content(self):
        status, data = self._get(self._file, params={'ref': BRANCH})
        if status == 404:
            return None, None
        if (not isinstance(data, dict)
                or data.get('type') != 'file'
                or data.get('path') != PATH
                or data.get('encoding') != 'base64'
                or not isinstance(data.get('sha'), str)
                or not SHA.fullmatch(data['sha'])
                or type(data.get('size')) is not int
                or not 1 <= data['size'] <= MAX_CIPHERTEXT_BYTES
                or not isinstance(data.get('content'), str)):
            raise ValueError('private checkpoint metadata is invalid')
        # GitHub may insert newlines between Base64 text chunks.
        encoded = data['content'].replace('\n', '')
        if len(encoded) > ((MAX_CIPHERTEXT_BYTES + 2) // 3) * 4:
            raise ValueError('private checkpoint is oversized')
        try:
            cipher = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error):
            raise ValueError('invalid checkpoint encoding') from None
        if len(cipher) != data['size']:
            raise ValueError('private checkpoint byte length mismatch')
        return cipher, data['sha']

    def read(self, *, key):
        """Return (private approved inventory, blob SHA), fail if not present."""
        self._validate_target()
        cipher, sha = self._fetch_content()
        if cipher is None:
            raise FileNotFoundError('private checkpoint not initialized')
        try:
            plaintext = _cipher(key).decrypt(cipher)
            if len(plaintext) > MAX_CIPHERTEXT_BYTES:
                raise ValueError('private snapshot too large')
            parsed = json.loads(plaintext)
            return _validated_set(parsed), sha
        except (InvalidToken, UnicodeError, json.JSONDecodeError):
            raise ValueError('private checkpoint decryption or structure invalid') from None

    def _write(self, *, key, approved_state, expected_sha):
        _validated_set(approved_state)
        plaintext = json.dumps(
            approved_state, sort_keys=True, ensure_ascii=False,
            separators=(',', ':'), allow_nan=False).encode('utf-8')
        if len(plaintext) > MAX_CIPHERTEXT_BYTES - 1024:
            raise ValueError('checkpoint exceeds approved size')
        cipher = _cipher(key).encrypt(plaintext)
        if len(cipher) > MAX_CIPHERTEXT_BYTES:
            raise ValueError('checkpoint ciphertext too large')
        payload = {
            'message': 'Update encrypted supplier checkpoint',
            'content': base64.b64encode(cipher).decode('ascii'),
            'branch': BRANCH,
        }
        if expected_sha is not None:
            payload['sha'] = expected_sha
        return self._put(payload)

    def initialize(self, *, key, approved_first_snapshot,
                   approve_initial_baseline=False):
        """Create once, only after explicitly accepting that old rows are not backfilled."""
        if approve_initial_baseline is not True:
            raise ValueError('initial checkpoint requires explicit approval')
        approved = finalize_inventory(
            None, approved_first_snapshot, approve_initial_baseline=True)
        self._validate_target()
        existing, _ = self._fetch_content()
        if existing is not None:
            raise FileExistsError('private checkpoint already initialized')
        return self._write(key=key, approved_state=approved, expected_sha=None)

    def advance_after_review(self, *, key, expected_sha, current_snapshot,
                             receipts, trusted_public_keys):
        """Verify all revision-specific Ed25519 receipts BEFORE a conditional PUT.

        Requires the last successfully read blob SHA, never a blind overwrite.
        Source revisions and actual reviewer identity must be authenticated
        externally. A remote write conflict HALTS; no automatic retry.
        """
        if not isinstance(expected_sha, str) or not SHA.fullmatch(expected_sha):
            raise ValueError('expected existing blob SHA is required')
        previous, observed_sha = self.read(key=key)
        if observed_sha != expected_sha:
            raise ValueError('stale inventory checkpoint revision')
        approved = finalize_with_offline_ed25519_receipts(
            previous, current_snapshot, receipts=receipts,
            trusted_public_keys=trusted_public_keys)
        if approved == previous:
            return {'written': False, 'unchanged': True}
        updated_sha = self._write(
            key=key, approved_state=approved, expected_sha=observed_sha)
        return {'written': True, 'new_blob_sha': updated_sha}
