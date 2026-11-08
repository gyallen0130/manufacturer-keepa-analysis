"""Read-only Google Drive metadata inventory and fail-closed change planning.

The caller supplies a narrowly scoped Drive v3 client and explicitly approved
folder IDs. Nothing here downloads documents, changes permissions, saves state,
or triggers the supplier parser. Treat snapshots and ID-bearing plans as private.
"""

import re

SCHEMA_VERSION = 'drive-inventory-v1'
FILE_ID = re.compile(r'^[A-Za-z0-9_-]{10,200}$')
FOLDER_MIME = 'application/vnd.google-apps.folder'
SUPPORTED_MIMES = frozenset({
    'application/vnd.google-apps.spreadsheet',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-excel.sheet.macroEnabled.12',
    'text/csv',
    'text/tab-separated-values',
})


def _valid_id(value):
    return isinstance(value, str) and bool(FILE_ID.fullmatch(value))


def scan_approved_folder(service, *, folder_id, max_pages=10,
                         max_items=500, page_size=100):
    """Take a complete, bounded snapshot of ONE explicitly approved folder.

    Only direct children are scanned; subfolders are counted but never opened.
    If pagination is incomplete/invalid, fail instead of interpreting missing
    entries as deletion. File names, contents and permissions are not requested.
    """
    if not _valid_id(folder_id):
        raise ValueError('invalid approved folder ID')
    if (type(max_pages) is not int or not 1 <= max_pages <= 100
            or type(max_items) is not int or not 1 <= max_items <= 10000
            or type(page_size) is not int or not 1 <= page_size <= 1000):
        raise ValueError('invalid scan bounds')

    seen_tokens = set()
    page_token = None
    entries = {}
    seen_files = set()
    total = ignored = subfolders = 0

    for page_index in range(max_pages):
        query = {
            'q': "'" + folder_id + "' in parents and trashed = false",
            'fields': 'nextPageToken,incompleteSearch,files(id,mimeType,modifiedTime,version,parents,trashed)',
            'pageSize': min(page_size, max_items),
            'supportsAllDrives': True,
            'includeItemsFromAllDrives': True,
        }
        if page_token:
            query['pageToken'] = page_token
        response = service.files().list(**query).execute()
        if not isinstance(response, dict) or response.get('incompleteSearch'):
            raise ValueError('incomplete Drive folder scan')
        files = response.get('files')
        if not isinstance(files, list):
            raise ValueError('invalid Drive list response')
        total += len(files)
        if total > max_items:
            raise ValueError('folder item limit exceeded')
        for item in files:
            if not isinstance(item, dict):
                raise ValueError('invalid Drive metadata item')
            file_id, mime = item.get('id'), item.get('mimeType')
            if (not _valid_id(file_id) or not isinstance(mime, str)
                    or file_id in seen_files or item.get('trashed') is True
                    or folder_id not in item.get('parents', ())):
                raise ValueError('untrusted or duplicate Drive metadata item')
            seen_files.add(file_id)
            if mime == FOLDER_MIME:
                subfolders += 1
                continue
            if mime not in SUPPORTED_MIMES:
                ignored += 1
                continue
            version = item.get('version')
            modified = item.get('modifiedTime')
            if version is None and not modified:
                raise ValueError('missing Drive change marker')
            if version is not None and (isinstance(version, bool)
                                        or not str(version).isdigit()):
                raise ValueError('invalid Drive version marker')
            if modified is not None and not isinstance(modified, str):
                raise ValueError('invalid Drive modification marker')
            entries[file_id] = {
                'mime_type': mime,
                'version': str(version) if version is not None else '',
                'modified_time': modified or '',
            }
        next_token = response.get('nextPageToken')
        if not next_token:
            return {
                'schema_version': SCHEMA_VERSION,
                'folder_id': folder_id,
                'files': entries,
                'total_items': total,
                'pages_scanned': page_index + 1,
                'unsupported_items': ignored,
                'unscanned_subfolders': subfolders,
            }
        if not isinstance(next_token, str) or next_token in seen_tokens:
            raise ValueError('invalid or repeated Drive pagination token')
        seen_tokens.add(next_token)
        page_token = next_token

    raise ValueError('Drive folder pagination limit exceeded')


def _validate_snapshot(snapshot):
    """Reject corrupt state before planning work; never print private IDs."""
    if not isinstance(snapshot, dict) or snapshot.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('unsupported or invalid inventory snapshot')
    if not _valid_id(snapshot.get('folder_id')):
        raise ValueError('invalid inventory folder')
    files = snapshot.get('files')
    if not isinstance(files, dict) or len(files) > 10000:
        raise ValueError('invalid inventory file map')
    for file_id, row in files.items():
        if (not _valid_id(file_id) or not isinstance(row, dict)
                or row.get('mime_type') not in SUPPORTED_MIMES
                or not isinstance(row.get('version'), str)
                or not isinstance(row.get('modified_time'), str)
                or not (row['version'] or row['modified_time'])):
            raise ValueError('invalid inventory file record')
    return files


def plan_changed_files(previous, current):
    """Return private IDs for later review, plus a redacted aggregate.

    None = first scan (baseline): no reprocessing is scheduled automatically.
    Missing files may be unshared or moved, so NEVER classify as deleted.
    The returned plan is inert: no network calls, writes or automatic actions.
    """
    new = _validate_snapshot(current)
    if previous is None:
        return {
            'is_baseline': True, 'candidate_file_ids': [],
            'unavailable_file_ids': [],
            'summary': {
                'baseline_count': len(new), 'new': 0, 'changed': 0,
                'unchanged': 0, 'unavailable_needs_review': 0,
                'unsupported_items': current.get('unsupported_items', 0),
                'unscanned_subfolders': current.get('unscanned_subfolders', 0),
            },
        }
    old = _validate_snapshot(previous)
    if previous['folder_id'] != current['folder_id']:
        raise ValueError('inventory folder mismatch')
    created = sorted(set(new) - set(old))
    changed = sorted(k for k in (set(old) & set(new)) if old[k] != new[k])
    unavailable = sorted(set(old) - set(new))
    unchanged = len(set(old) & set(new)) - len(changed)
    return {
        'is_baseline': False,
        'candidate_file_ids': created + changed,
        'unavailable_file_ids': unavailable,
        'summary': {
            'baseline_count': 0, 'new': len(created), 'changed': len(changed),
            'unchanged': unchanged,
            'unavailable_needs_review': len(unavailable),
            'unsupported_items': current.get('unsupported_items', 0),
            'unscanned_subfolders': current.get('unscanned_subfolders', 0),
        },
    }


def scan_explicit_folder_set(service, *, folder_ids, max_folders=160,
                             max_total_pages=240, max_total_items=10000):
    """Scan ONLY explicitly supplied folders, never recurse or search My Drive.

    Intended for a private per-supplier allowlist after separate consent and
    permissions. One inaccessible/over-limit folder aborts the *entire* scan;
    a partial snapshot must never overwrite a complete baseline.
    """
    if (not isinstance(folder_ids, (list, tuple))
            or not folder_ids or len(folder_ids) > max_folders
            or any(not _valid_id(folder_id) for folder_id in folder_ids)
            or len(set(folder_ids)) != len(folder_ids)):
        raise ValueError('invalid or duplicate approved folder list')
    if (type(max_folders) is not int or not 1 <= max_folders <= 200
            or type(max_total_pages) is not int or not 1 <= max_total_pages <= 1000
            or type(max_total_items) is not int or not 1 <= max_total_items <= 50000):
        raise ValueError('invalid batch scan bounds')

    snapshots = {}
    pages = 0
    total = 0
    file_ids = set()
    for folder_id in folder_ids:
        if pages == max_total_pages or total == max_total_items:
            raise ValueError('approved folder set limit exceeded')
        snapshot = scan_approved_folder(
            service, folder_id=folder_id,
            max_pages=min(10, max_total_pages - pages),
            max_items=min(500, max_total_items - total),
        )
        pages += snapshot['pages_scanned']
        total += snapshot['total_items']
        if file_ids.intersection(snapshot['files']):
            raise ValueError('duplicate document in approved folder set')
        file_ids.update(snapshot['files'])
        snapshots[folder_id] = snapshot
    return snapshots


def plan_explicit_folder_set(previous, current):
    """Aggregate *inert* per-folder delta plans with no private IDs in summary."""
    if not isinstance(current, dict) or not current:
        raise ValueError('invalid current folder set')
    if previous is not None and (
            not isinstance(previous, dict) or set(previous) != set(current)):
        raise ValueError('approved folder set changed; manual rebaseline required')

    summary = {
        'baseline_count': 0, 'new': 0, 'changed': 0, 'unchanged': 0,
        'unavailable_needs_review': 0, 'unsupported_items': 0,
        'unscanned_subfolders': 0,
    }
    pending = []
    unavailable = []
    for folder_id, snapshot in current.items():
        if not _valid_id(folder_id) or snapshot.get('folder_id') != folder_id:
            raise ValueError('invalid inventory folder set')
        before = previous[folder_id] if previous is not None else None
        one = plan_changed_files(before, snapshot)
        for key in summary:
            summary[key] += one['summary'][key]
        pending.extend((folder_id, fid) for fid in one['candidate_file_ids'])
        unavailable.extend((folder_id, fid) for fid in one['unavailable_file_ids'])
    return {
        'is_baseline': previous is None,
        'candidate_locations': pending,
        'unavailable_locations': unavailable,
        'summary': summary,
    }
