"""Keyless, delegated Sheets read-only identity for supplier document smoke tests.

Do not re-use the production SP-API/Drive identity or place credential keys in Git.
Only the impersonated token is attached to the Sheets service.
"""
import re

SHEETS_READONLY_SCOPE = 'https://www.googleapis.com/auth/spreadsheets.readonly'
DRIVE_METADATA_READONLY_SCOPE = 'https://www.googleapis.com/auth/drive.metadata.readonly'
_SERVICE_ACCOUNT_PATTERN = re.compile(
    r'^[a-z][a-z0-9-]{0,29}@[a-z][a-z0-9-]{4,61}\.iam\.gserviceaccount\.com$'
)


def build_readonly_sheets_service(service_account_email, *, source_credentials=None):
    """Use user ADC to impersonate a dedicated SA with only Sheets read scope.

    The source credentials need IAM Service Account Token Creator on *this*
    dedicated service account and may have wider scopes themselves. Only
    impersonated credentials with a restricted target scope reach Sheets.
    The target SA also needs Viewer access to the exact test spreadsheet.
    """
    if not isinstance(service_account_email, str) or not _SERVICE_ACCOUNT_PATTERN.fullmatch(
        service_account_email
    ):
        raise ValueError('An explicit, valid service-account email is required')

    import google.auth
    from google.auth import impersonated_credentials
    from googleapiclient.discovery import build

    if source_credentials is None:
        source_credentials, _ = google.auth.default()
    target_credentials = impersonated_credentials.Credentials(
        source_credentials=source_credentials,
        target_principal=service_account_email,
        target_scopes=[SHEETS_READONLY_SCOPE],
        lifetime=900,  # short-lived 15 minute token; never persist this token
    )
    return build('sheets', 'v4', credentials=target_credentials, cache_discovery=False)



def build_readonly_drive_metadata_service(service_account_email, *,
                                          source_credentials=None):
    """Use a dedicated short-lived target token for Drive metadata only.

    This requires Drive API enablement, an explicit reader-SA file/folder
    share and a SA-specific Token Creator grant. The source credential can
    come from Cloud Run's runtime identity, without exporting JSON keys.
    This does NOT grant access to additional Drive files or the root folder.
    """
    if (not isinstance(service_account_email, str)
            or not _SERVICE_ACCOUNT_PATTERN.fullmatch(service_account_email)):
        raise ValueError('An explicit, valid service-account email is required')

    import google.auth
    from google.auth import impersonated_credentials
    from googleapiclient.discovery import build

    if source_credentials is None:
        source_credentials, _ = google.auth.default()
    delegated = impersonated_credentials.Credentials(
        source_credentials=source_credentials,
        target_principal=service_account_email,
        target_scopes=[DRIVE_METADATA_READONLY_SCOPE],
        lifetime=900,
    )
    return build('drive', 'v3', credentials=delegated, cache_discovery=False)


def build_readonly_sheets_service_from_wif_adc():
    """Use ONLY the OAuth scope requested for a trusted PRIVATE GitHub WIF job.

    A separately reviewed GitHub WIF provider must restrict the immutable
    repository ID, ref, workflow_ref and event to manual dispatch. This client
    builder does NOT verify Google IAM or source-credential identity by itself.

    Unlike the Colab flow, the Github auth action directly impersonates the
    dedicated Reader SA. No second SA/token-creator grant is required here.
    The Reader must have Viewer access to approved Sheets only.
    """
    import google.auth
    from googleapiclient.discovery import build

    credentials, _ = google.auth.default(scopes=[SHEETS_READONLY_SCOPE])
    return build('sheets', 'v4', credentials=credentials,
                 cache_discovery=False)
