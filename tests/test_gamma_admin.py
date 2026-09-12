import json
import unittest
from unittest.mock import Mock
from gamma_admin import MattermostAdmin


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.owner = {'user_id': 'a' * 26, 'username': 'gamma-e2e-123456abcd',
                      'email': 'gamma-e2e-123456abcd@example.invalid'}
        self.user = {'id': self.owner['user_id'], 'username': self.owner['username'],
                     'email': self.owner['email'], 'roles': 'system_user', 'delete_at': 0}
        self.access = Mock(namespace='default')
        self.access.assert_dev_gamma = Mock()
        self.access.remote.return_value = json.dumps({'ServiceSettings': {
            'EnableLocalMode': True, 'LocalModeSocketLocation': '/mattermost/run/mattermost_local.socket'}})
        self.access.resource.return_value = {'metadata': {'uid': 'fixed'}}
        self.admin = MattermostAdmin(self.access)
        self.admin.command = Mock()

    def test_deactivates_verified_ordinary_fixture(self):
        self.admin.command.side_effect = [json.dumps(self.user), '{}', json.dumps({**self.user, 'delete_at': 1})]
        guard = Mock()
        receipt = self.admin.deactivate_fixture(self.owner, guard)
        self.assertTrue(receipt['account_inactive_verified'])
        guard.assert_called_once()
        self.admin.command.assert_any_call('user', 'deactivate', self.owner['user_id'])

    def test_idempotent_inactive_account(self):
        self.admin.command.return_value = json.dumps({**self.user, 'delete_at': 1})
        receipt = self.admin.deactivate_fixture(self.owner, Mock())
        self.assertTrue(receipt['already_inactive'])
        self.assertEqual(self.admin.command.call_count, 2)

    def test_rejects_administrators_bots_and_foreign_identity(self):
        for change in ({'roles': 'system_user system_admin'}, {'is_bot': True},
                       {'username': 'someone'}, {'email': 'other@example.invalid'}, {'id': 'b' * 26}):
            self.admin.command.reset_mock()
            self.admin.command.return_value = json.dumps({**self.user, **change})
            with self.assertRaises(PermissionError):
                self.admin.deactivate_fixture(self.owner, Mock())
            self.assertEqual(self.admin.command.call_count, 1)

    def test_expired_lease_prevents_administrative_mutation(self):
        self.admin.command.return_value = json.dumps(self.user)
        with self.assertRaises(PermissionError):
            self.admin.deactivate_fixture(self.owner, Mock(side_effect=PermissionError('expired')))
        self.assertEqual(self.admin.command.call_count, 1)

    def test_external_deployment_replacement_stops_cleanup(self):
        self.admin.command.return_value = json.dumps(self.user)
        self.access.resource.return_value = {'metadata': {'uid': 'replacement'}}
        with self.assertRaises(RuntimeError):
            self.admin.deactivate_fixture(self.owner, Mock())
        self.assertEqual(self.admin.command.call_count, 1)

    def test_false_success_is_rejected(self):
        self.admin.command.return_value = json.dumps(self.user)
        with self.assertRaises(RuntimeError):
            self.admin.deactivate_fixture(self.owner, Mock())

    def test_disabled_local_admin_is_not_enabled_implicitly(self):
        self.access.remote.return_value = json.dumps({'ServiceSettings': {'EnableLocalMode': False}})
        with self.assertRaises(RuntimeError):
            MattermostAdmin(self.access)

    def test_other_cluster_is_rejected_before_reading_admin_configuration(self):
        self.access.remote.reset_mock()
        self.access.assert_dev_gamma.side_effect = PermissionError('not dev-gamma')
        with self.assertRaises(PermissionError):
            MattermostAdmin(self.access)
        self.access.remote.assert_not_called()
