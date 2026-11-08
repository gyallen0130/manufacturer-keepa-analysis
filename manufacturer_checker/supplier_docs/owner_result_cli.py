"""Offline owner-side interactive CLI for Google Sheets encrypted GitHub results.

Run only on the owner's trusted local machine, never in GitHub Actions,
Colab or background jobs. Passwords are read only by getpass in a real TTY;
no CLI password flags, environment secrets or stdin pipe. Raw supplier data
is never printed. Explicit export creates a protected plaintext file ONCE.

This is a development/pilot entrypoint: Windows NTFS ACL, disk encryption,
cloud-sync exclusion and trusted recipient fingerprint need external review.
"""
import argparse
import getpass
import json
import sys

from .owner_key_vault import (
    create_owner_key_vault, read_owner_encrypted_artifact,
    export_owner_inspections,
)


class _PrivateParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'Unsupported options; no secrets allowed as arguments.\n')


def parser():
    p = _PrivateParser(
        description='Offline owner-key creation and encrypted supplier result reader.',
        allow_abbrev=False)
    s = p.add_subparsers(dest='operation', required=True,
                         parser_class=_PrivateParser)
    init = s.add_parser('init-key', allow_abbrev=False)
    init.add_argument('--vault', required=True)
    for name in ('inspect', 'export'):
        command = s.add_parser(name, allow_abbrev=False)
        command.add_argument('--vault', required=True)
        command.add_argument('--artifact', required=True)
        command.add_argument('--trusted-fingerprint', required=True)
        if name == 'export':
            command.add_argument('--output', required=True)
    return p


def _confirm(ask, label, word):
    if ask(label + ' Type ' + word + ' to confirm: ') != word:
        raise PermissionError('explicit owner confirmation required')


def perform(options, *, password_reader, confirmation_reader):
    """Dependency-injected tests; NEVER output a plaintext record."""
    if options.operation not in ('init-key', 'inspect', 'export'):
        raise ValueError('unsupported owner action')
    import os
    if os.name == 'nt':
        _confirm(
            confirmation_reader,
            'Private local folder NTFS ACL, encryption and non-sync checked.',
            'WINDOWS-REVIEWED')
    else:
        _confirm(
            confirmation_reader,
            'Owner-only 0700 local folder and private device checked.',
            'LOCAL-REVIEWED')
    if options.operation == 'init-key':
        _confirm(
            confirmation_reader,
            'Generate a NEW private key, without existing encrypted reports. '
            'Backup the encrypted vault separately from its passphrase.',
            'CREATE-OWNER-KEY')
        password = password_reader('New long vault passphrase (hidden): ')
        repeated = password_reader('Repeat vault passphrase (hidden): ')
        if not isinstance(password, str) or password != repeated:
            raise ValueError('vault passphrase confirmation did not match')
        return create_owner_key_vault(
            options.vault, passphrase=password,
            approve_key_creation=True, windows_storage_reviewed=True)
    password = password_reader('Vault passphrase (hidden): ')
    if not isinstance(password, str):
        raise ValueError('private passphrase input required')
    if options.operation == 'inspect':
        report = read_owner_encrypted_artifact(
            options.vault, options.artifact, passphrase=password,
            trusted_fingerprint_sha256=options.trusted_fingerprint,
            windows_storage_reviewed=True)
        summary = report['public_summary']
        if type(summary.get('normalized_records')) is not int:
            raise ValueError('inspection summary missing row count')
        return {
            'operation': 'inspect',
            'decryption_verified': True,
            'normalized_records': summary['normalized_records'],
            'plaintext_records_logged': False,
            'files_created': 0,
            'api_calls': 0,
        }
    _confirm(
        confirmation_reader,
        'Creates a new PLAINTEXT supplier record file. Confirm private '
        'local destination, no cloud sync, no existing file.',
        'EXPORT-PRIVATE-PLAINTEXT')
    report = export_owner_inspections(
        options.vault, options.artifact, options.output,
        passphrase=password,
        trusted_fingerprint_sha256=options.trusted_fingerprint,
        approve_plaintext_export=True, windows_storage_reviewed=True)
    return {'operation': 'export', **report}


def main(argv=None, *, stdin=None, stderr=None, stdout=None,
         confirmation_reader=None, password_reader=None):
    error_stream = sys.stderr if stderr is None else stderr
    output_stream = sys.stdout if stdout is None else stdout
    incoming = sys.stdin if stdin is None else stdin
    options = parser().parse_args(argv)
    if not incoming.isatty() or not error_stream.isatty():
        error_stream.write('Interactive local terminal required; no operation.\n')
        return 2
    try:
        result = perform(
            options,
            password_reader=getpass.getpass if password_reader is None
            else password_reader,
            confirmation_reader=input if confirmation_reader is None
            else confirmation_reader)
    except Exception:
        # Do not echo file names, Google API values, paths, passwords, or
        # credential parser tracebacks in logs.
        error_stream.write('Owner result operation refused. Check private '
                           'storage, trusted key pin and input locally.\n')
        return 1
    output_stream.write(
        json.dumps(result, sort_keys=True, ensure_ascii=True) + '\n')
    return 0


if __name__ == '__main__':
    if len(sys.argv) == 1:
        sys.stderr.write('Specify init-key, inspect, or export.\n')
        raise SystemExit(2)
    raise SystemExit(main())
