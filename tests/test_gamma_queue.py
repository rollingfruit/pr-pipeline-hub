import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from gamma_queue import validate, assert_lease, update_environment, SUITES


class GammaQueueTests(unittest.TestCase):
    def body(self):
        return {'submission_id': 'trial-1', 'environment_id': 'env-1',
                'mode': 'stability', 'rounds': 30, 'suite_ids': list(SUITES)}

    def test_stability_freezes_full_set(self):
        self.assertEqual(validate(self.body())[1], 'stability')
        self.assertEqual(validate({**self.body(), 'rounds': 10})[1], 'stability')
        for patch in ({'rounds': 29}, {'rounds': True}, {'rounds': '10'}, {'suite_ids': ['E01']}, {'suite_ids': []}, {'mode': 'unknown'}):
            with self.assertRaises(ValueError):
                validate({**self.body(), **patch})

    def test_rejects_manifest_outside_owned_directory(self):
        with self.assertRaises(ValueError):
            validate({**self.body(), 'build_manifest': '/tmp/request.json'})

    def row(self):
        until = datetime.now(timezone.utc) + timedelta(seconds=180)
        return {'holder': 'job', 'state': 'running', 'run_state': 'running', 'lease_until': until,
                'run_until': until, 'lease_token': 'secret', 'run_token': 'secret', 'generation': 4}

    def test_old_generation_and_expired_lease_rejected(self):
        for change, generation in (({}, 3), ({'lease_token': 'other'}, 4),
                                   ({'state': 'quarantined'}, 4),
                                   ({'lease_until': datetime.now(timezone.utc)}, 4)):
            db = Mock()
            db.execute.return_value.fetchone.return_value = {**self.row(), **change}
            with self.assertRaises(PermissionError):
                assert_lease(db, 'job', 'secret', generation)

    def test_cleanup_failure_quarantines_and_preserves_holder(self):
        db = Mock()
        db.execute.return_value.fetchone.return_value = self.row()
        result = {'status': 'completed', 'cleanup': {'status': 'failed'}, 'environment_health': 'ready'}
        update_environment(db, 'job', 'secret', result, True)
        self.assertEqual(result['status'], 'interrupted')
        self.assertIn("state='quarantined'", db.execute.call_args.args[0])
        self.assertNotIn('holder=NULL', db.execute.call_args.args[0])

    def test_clean_completion_releases_environment(self):
        db = Mock()
        db.execute.return_value.fetchone.return_value = self.row()
        update_environment(db, 'job', 'secret', {'cleanup': {'status': 'passed', 'active_residuals': []}, 'environment_health': 'ready'}, True)
        self.assertIn('holder=NULL', db.execute.call_args.args[0])

    def test_green_cleanup_without_residual_inventory_cannot_release(self):
        for residuals in (None, [{'kind': 'daemon', 'id': 'leftover'}]):
            db = Mock()
            db.execute.return_value.fetchone.return_value = self.row()
            patch = {'status': 'completed', 'cleanup': {'status': 'passed', 'active_residuals': residuals},
                     'environment_health': 'ready'}
            update_environment(db, 'job', 'secret', patch, True)
            self.assertEqual(patch['status'], 'interrupted')
