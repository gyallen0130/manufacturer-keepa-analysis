"""Strict Google Drive v3 file-version evidence for PRIVATE supplier scans.

The provider obtains raw Drive v3 files.get metadata with fields exactly
'id,mimeType,version' under an INDEPENDENTLY authenticated, authorized
read-only Google client. This module makes no network calls, stores no
credentials and never interprets modifiedTime or revisions.list as equivalent
to the monotonic Drive file version.

Google Drive v3 'version' is returned as a decimal int64 *string*.
https://developers.google.com/workspace/drive/api/reference/rest/v3/files
"""
from .drive_delta import FILE_ID

DRIVE_VERSION_KIND = 'google_drive_v3_monotonic_file_version'
GOOGLE_SHEET_MIME = 'application/vnd.google-apps.spreadsheet'
FIELDS = 'id,mimeType,version'
MAX_I64 = 9223372036854775807


def strict_drive_v3_version(*, metadata, expected_file_id):
    """Convert an externally authenticated raw files.get response to evidence.

    Missing version, ambiguous custom tokens, old timestamps, and revisions
    are deliberately rejected, rather than silently weakening guarantees.
    This validates the SHAPE and binding only, not Google authentication.
    """
    if (not isinstance(expected_file_id, str)
            or not FILE_ID.fullmatch(expected_file_id)):
        raise ValueError('invalid expected private Google file id')
    if (not isinstance(metadata, dict)
            or set(metadata) != {'id', 'mimeType', 'version'}):
        raise ValueError('Drive v3 raw version metadata required')
    if metadata['id'] != expected_file_id:
        raise ValueError('Drive file identity changed')
    if metadata['mimeType'] != GOOGLE_SHEET_MIME:
        raise ValueError('Drive file is not a native Google Sheet')
    version = metadata['version']
    # JSON int64 is represented as a decimal string. Numeric JS values can
    # lose precision above 2^53; never rely on them as a revision witness.
    if (not isinstance(version, str) or not 1 <= len(version) <= 19
            or version[0] == '0' or not version.isascii()
            or not version.isdecimal()
            or int(version) > MAX_I64):
        raise ValueError('Google Drive monotonic version unavailable')
    return {
        'spreadsheet_id': expected_file_id,
        'revision_kind': DRIVE_VERSION_KIND,
        'version': version,
    }


def make_drive_v3_version_adapter(authenticated_raw_files_get):
    """Adapt an authenticated Google Drive v3 files.get reader.

    The callback contract is:
      authenticated_raw_files_get(file_id=<id>, fields='id,mimeType,version')
    It MUST raise if the call is unauthorized or fails. It MUST return the
    unprojected Google API dict including version, not ChatGPT's currently
    projected Drive metadata object. Its caller checks the OAuth identity,
    source access and private-only response destination.
    """
    if not callable(authenticated_raw_files_get):
        raise ValueError('authenticated raw Drive v3 reader required')

    def get_source_revision(*, spreadsheet_id):
        if not isinstance(spreadsheet_id, str) or not FILE_ID.fullmatch(spreadsheet_id):
            raise ValueError('invalid selected Google file id')
        try:
            response = authenticated_raw_files_get(
                file_id=spreadsheet_id, fields=FIELDS)
        except Exception:
            # Do not leak a credential, signed URL or original file name
            # contained in a network/client exception into a shared log.
            raise RuntimeError('authorized Drive version read failed') from None
        return strict_drive_v3_version(
            metadata=response, expected_file_id=spreadsheet_id)
    return get_source_revision
