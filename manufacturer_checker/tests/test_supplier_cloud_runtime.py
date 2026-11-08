"""Fake manifests only. No Google Cloud credentials or resource changes."""
import json
import unittest

from supplier_docs.cloud_runtime import validate_supplier_cloud_runtime

PROJECT = 'fake-supplier-project'


def proposed():
    return {
        'project_id': PROJECT,
        'region': 'asia-northeast1',
        'job_name': 'supplier-docs-inventory',
        'worker_sa': 'supplier-docs-worker@' + PROJECT + '.iam.gserviceaccount.com',
        'reader_sa': 'supplier-docs-reader@' + PROJECT + '.iam.gserviceaccount.com',
        'review_sa': 'supplier-docs-review@' + PROJECT + '.iam.gserviceaccount.com',
        'scheduler_sa': 'supplier-docs-trigger@' + PROJECT + '.iam.gserviceaccount.com',
        'state_bucket': 'supplier-docs-state-test-example',
        'state_encryption_secret': 'projects/' + PROJECT +
                                   '/secrets/supplier-docs-inventory-key/versions/1',
        'journal_encryption_secret': 'projects/' + PROJECT +
                                     '/secrets/supplier-docs-review-journal-key/versions/1',
        'review_signing_secret': 'projects/' + PROJECT +
                                 '/secrets/supplier-docs-review-signing-key/versions/2',
        'mode': 'dry_run',
        'schedule_enabled': False,
        'max_parallelism': 1,
        'max_retries': 0,
        'raw_data_logging': False,
        'automatic_review': False,
        'recursive_drive_scan': False,
    }


class SupplierCloudRuntimeTests(unittest.TestCase):
    def test_valid_dry_run_returns_anonymous_no_change_summary(self):
        cfg = proposed()
        result = validate_supplier_cloud_runtime(cfg)
        self.assertEqual(result['separate_identities'], 4)
        self.assertFalse(result['cloud_changes_made'])
        self.assertEqual(result['operation'], 'offline_preflight_only')
        for private_value in cfg.values():
            if isinstance(private_value, str):
                self.assertNotIn(private_value,
                                 json.dumps(result, ensure_ascii=False))

    def test_existing_spapi_names_are_not_accepted(self):
        cfg = proposed()
        cfg['worker_sa'] = 'amazon-spapi-drive@' + PROJECT + '.iam.gserviceaccount.com'
        with self.assertRaises(ValueError):
            validate_supplier_cloud_runtime(cfg)
        cfg = proposed()
        cfg['job_name'] = 'spapi-supplier-docs-inventory'
        with self.assertRaises(ValueError):
            validate_supplier_cloud_runtime(cfg)

    def test_separate_service_identities_are_required(self):
        for field, replacement in [
            ('reader_sa', 'supplier-docs-worker'),
            ('scheduler_sa', 'supplier-docs-review'),
            ('review_sa', 'supplier-docs-trigger'),
        ]:
            cfg = proposed()
            cfg[field] = replacement + '@' + PROJECT + '.iam.gserviceaccount.com'
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_supplier_cloud_runtime(cfg)

    def test_secrets_must_be_independent_and_version_pinned(self):
        for field in ('state_encryption_secret', 'journal_encryption_secret',
                      'review_signing_secret'):
            cfg = proposed()
            cfg[field] = cfg[field].replace('/versions/1', '/versions/latest').replace(
                '/versions/2', '/versions/latest')
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_supplier_cloud_runtime(cfg)
        cfg = proposed()
        cfg['journal_encryption_secret'] = cfg['state_encryption_secret']
        with self.assertRaises(ValueError):
            validate_supplier_cloud_runtime(cfg)

    def test_unsafe_scheduler_logging_and_auto_actions_rejected(self):
        for field in ('schedule_enabled', 'raw_data_logging', 'automatic_review',
                      'recursive_drive_scan'):
            cfg = proposed()
            cfg[field] = True
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_supplier_cloud_runtime(cfg)
        cfg = proposed()
        cfg['mode'] = 'live'
        with self.assertRaises(ValueError):
            validate_supplier_cloud_runtime(cfg)

    def test_parallelism_and_retries_require_explicit_safety(self):
        for field, value in [('max_parallelism', 2), ('max_parallelism', True),
                             ('max_retries', 1), ('max_retries', False)]:
            cfg = proposed()
            cfg[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_supplier_cloud_runtime(cfg)

    def test_no_extra_keys_or_unrelated_project_bucket_accepted(self):
        cfg = proposed()
        cfg['service_account_private_key'] = 'not-permitted'
        with self.assertRaises(ValueError):
            validate_supplier_cloud_runtime(cfg)
        cfg = proposed()
        cfg['state_bucket'] = 'amazon-spapi-inventory-bucket'
        with self.assertRaises(ValueError):
            validate_supplier_cloud_runtime(cfg)
        cfg = proposed()
        cfg['reader_sa'] = 'supplier-docs-reader@other-project.iam.gserviceaccount.com'
        with self.assertRaises(ValueError):
            validate_supplier_cloud_runtime(cfg)


if __name__ == '__main__':
    unittest.main()
