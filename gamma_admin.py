"""Scoped system administration using Mattermost's existing local management socket."""
import json
import re
import shlex


class MattermostAdmin:
    def __init__(self, access):
        self.access = access
        access.assert_dev_gamma()
        config = json.loads(access.remote('kubectl -n ' + shlex.quote(access.namespace) +
                                         ' exec deployment/mattermost -- cat /mattermost/config/config.json'))
        settings = config.get('ServiceSettings', {})
        if settings.get('EnableLocalMode') is not True:
            raise RuntimeError('Mattermost local administrative mode is not enabled')
        self.socket = settings.get('LocalModeSocketLocation')
        if self.socket != '/mattermost/run/mattermost_local.socket':
            raise RuntimeError('Unexpected Mattermost administration socket; configuration review required')
        self.uid = access.resource('deployment', 'mattermost')['metadata']['uid']

    def command(self, *args):
        command = ['kubectl', '-n', self.access.namespace, 'exec', 'deployment/mattermost', '--',
                   'env', 'MMCTL_LOCAL_SOCKET_PATH=' + self.socket,
                   '/mattermost/bin/mmctl', '--local', '--json', *args]
        return self.access.remote(shlex.join(command))

    def fixture(self, expected):
        identifier = expected.get('user_id', '')
        username = expected.get('username', '')
        if (not re.fullmatch(r'[a-z0-9]{26}', identifier)
                or not re.fullmatch(r'gamma-e2e-[a-f0-9]{10}', username)
                or expected.get('email') != username + '@example.invalid'):
            raise ValueError('Owned Gamma fixture identity is required')
        user = json.loads(self.command('user', 'search', identifier))
        if (not isinstance(user, dict) or user.get('id') != identifier or user.get('username') != username
                or user.get('email') != expected['email'] or user.get('is_bot')
                or 'system_admin' in user.get('roles', '').split()):
            raise PermissionError('Fixture ownership or non-administrator identity mismatch')
        return user

    def deactivate_fixture(self, expected, guard):
        user = self.fixture(expected)
        already_inactive = bool(user.get('delete_at'))
        if not already_inactive:
            guard()
            if self.access.resource('deployment', 'mattermost')['metadata']['uid'] != self.uid:
                raise RuntimeError('Mattermost deployment changed before administrative cleanup')
            self.command('user', 'deactivate', expected['user_id'])
        after = self.fixture(expected)
        if not after.get('delete_at'):
            raise RuntimeError('Test account remains active after administrative cleanup')
        return {'kind': 'test_account_deactivated', 'id': expected['user_id'],
                'already_inactive': already_inactive, 'method': 'mattermost_mmctl_local',
                'account_inactive_verified': True}
