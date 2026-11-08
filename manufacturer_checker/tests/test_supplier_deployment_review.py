"""Offline IAM proposals using fictional identities; no Google Cloud calls."""
import json
import unittest
from copy import deepcopy

from supplier_docs.deployment_review import (
    plan_supplier_iam, validate_exact_iam_proposal,
)

PROJECT = 'fake-supplier-project'


def proposal():
    base = 'supplier-docs-'
    suffix = '@' + PROJECT + '.iam.gserviceaccount.com'
    secret = 'projects/' + PROJECT + '/secrets/' + base
    return {
        'project_id': PROJECT, 'region': 'asia-northeast1',
        'job_name': base + 'inventory',
        'worker_sa': base + 'worker' + suffix,
        'reader_sa': base + 'reader' + suffix,
        'review_sa': base + 'review' + suffix,
        'scheduler_sa': base + 'trigger' + suffix,
        'state_bucket': base + 'state-synthetic',
        'review_bucket': base + 'review-synthetic',
        'state_encryption_secret': secret + 'inventory-key/versions/1',
        'journal_encryption_secret': secret + 'journal-key/versions/1',
        'review_signing_secret': secret + 'signing-key/versions/1',
        'mode': 'dry_run', 'schedule_enabled': False,
        'max_parallelism': 1, 'max_retries': 0,
        'raw_data_logging': False, 'automatic_review': False,
        'recursive_drive_scan': False,
    }


class SupplierIAMReviewTests(unittest.TestCase):

    def test_roles_are_resource_scoped_and_do_not_grant_spapi(self):
        cfg = proposal()
        plan = plan_supplier_iam(cfg)
        bindings = plan['private_bindings']
        self.assertEqual(len(bindings), 8)
        self.assertTrue(plan['summary']['blocked_until_human_approval'])
        self.assertTrue(plan['summary']['blocked_until_safe_review_handoff_and_recovery'])
        self.assertEqual(plan['summary']['permission_grants_performed'], 0)
        self.assertNotIn(PROJECT, json.dumps(plan['summary']))
        for b in bindings:
            self.assertNotIn('spapi', json.dumps(b))
            self.assertNotIn('roles/owner', b['role'])
            self.assertNotIn('roles/editor', b['role'])
            self.assertNotIn('roles/storage.admin', b['role'])
            self.assertNotEqual(b['resource'], 'projects/' + PROJECT)
            self.assertTrue(b['resource'].startswith(('projects/_/buckets/',
                                                       'projects/' + PROJECT + '/')))
        self.assertEqual([x for x in bindings if x['deferred']][0]['role'],
                         'roles/run.invoker')

    def test_worker_cannot_sign_or_read_review_journal(self):
        cfg = proposal()
        bindings = plan_supplier_iam(cfg)['private_bindings']
        worker = [b for b in bindings if b['principal'] == cfg['worker_sa']]
        self.assertEqual(len(worker), 3)
        self.assertNotIn(cfg['review_bucket'], json.dumps(worker))
        self.assertNotIn('supplier-docs-signing-key', json.dumps(worker))
        reviewer = [b for b in bindings if b['principal'] == cfg['review_sa']]
        self.assertEqual(len(reviewer), 4)
        self.assertFalse(any(b['role'] == 'roles/storage.objectUser'
                             and cfg['state_bucket'] in b['resource']
                             for b in reviewer))
        self.assertTrue(any(b['role'] == 'roles/storage.objectViewer'
                            and cfg['state_bucket'] in b['resource']
                            for b in reviewer))

    def test_exact_binding_proposal_is_accepted_without_cloud_changes(self):
        cfg = proposal()
        rows = plan_supplier_iam(cfg)['private_bindings']
        result = validate_exact_iam_proposal(cfg, deepcopy(rows))
        self.assertEqual(result, {
            'valid_proposal': True, 'changes_applied': False,
            'requires_human_approval': True,
        })

    def test_project_wide_or_extra_privileges_are_rejected(self):
        cfg = proposal()
        rows = plan_supplier_iam(cfg)['private_bindings']
        for edited in [
            rows[:-1],
            rows + [{**rows[0], 'role': 'roles/owner',
                     'resource': 'projects/' + PROJECT}],
            [{**rows[0], 'resource': 'projects/' + PROJECT}, *rows[1:]],
            [{**rows[0], 'role': 'roles/iam.serviceAccountAdmin'}, *rows[1:]],
            [*rows[1:], rows[0]],
        ]:
            with self.subTest(edited=edited), self.assertRaises(ValueError):
                validate_exact_iam_proposal(cfg, edited)

    def test_missing_bucket_or_live_schedule_rejected(self):
        for key, value in [
            ('review_bucket', None),
            ('review_bucket', 'supplier-docs-state-synthetic'),
            ('schedule_enabled', True),
            ('mode', 'live'),
            ('worker_sa', 'amazon-spapi-admin@' + PROJECT +
             '.iam.gserviceaccount.com'),
        ]:
            cfg = proposal()
            cfg[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                plan_supplier_iam(cfg)


if __name__ == '__main__':
    unittest.main()
