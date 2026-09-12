"""Isolated administrative capability diagnostic, not an E01-E06 stability round."""
import fcntl
import json
from pathlib import Path
import secrets
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, '/opt/gamma-p0-validation/hub')
sys.path.append('/opt/pr-pipeline-ci')
from gamma_access import GammaAccess
from gamma_admin import MattermostAdmin

run_id = 'admin-check-' + time.strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3)
root = Path('/var/lib/pr-gamma-admin-checks') / run_id
root.mkdir(parents=True, mode=0o700)
root.chmod(0o700)
report = {'id': run_id, 'kind': 'administrative_diagnostic', 'formal_round': False, 'status': 'running'}
access = GammaAccess('a5932430eb2f')
lock = Path('/var/lib/pr-e2e/gamma-diagnostics/dev-gamma.lock').open('a')
token = ''
owner = None
admin = None


def guard():
    worker_token = Path('/etc/pr-e2e/secrets/worker-token').read_text().strip()
    with urlopen(Request('http://127.0.0.1:8792/api/runs', headers={'X-Worker-Token': worker_token}), timeout=15) as response:
        data = json.load(response)
    runs = data.get('runs', []) if isinstance(data, dict) else data
    if any(r.get('status') in ('running', 'interrupted') for r in runs):
        raise RuntimeError('An execution needs the environment; administrative diagnostic deferred')
    current = access.resource('deployment', 'mattermost')
    if current['metadata']['uid'] != deployment['metadata']['uid'] or current['spec']['template'] != deployment['spec']['template']:
        raise RuntimeError('Mattermost changed during administrative diagnostic')


def api(route, data=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request(base + route, data=None if data is None else json.dumps(data).encode(), headers=headers)
    with urlopen(request, timeout=30) as response:
        return json.load(response), response.headers


try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    access.connect()
    deployment = access.resource('deployment', 'mattermost')
    guard()
    admin = MattermostAdmin(access)
    router = next(s for s in access.resource('services')['items']
                  if s['spec'].get('selector', {}).get('app') == 'service-router')
    base = access.forward(router['spec']['clusterIP'], 80, 0)
    username = 'gamma-e2e-' + secrets.token_hex(5)
    password = secrets.token_urlsafe(32) + '!7aA'
    user, _ = api('/api/v4/users', {'username': username, 'email': username + '@example.invalid', 'password': password})
    owner = {'run_id': run_id, 'user_id': user['id'], 'username': username, 'email': username + '@example.invalid'}
    (root / 'ownership.json').write_text(json.dumps(owner))
    (root / 'ownership.json').chmod(0o600)
    user, headers = api('/api/v4/users/login', {'login_id': username, 'password': password})
    token = headers['Token']
    report['test_roles'] = user['roles']
    if 'system_admin' in user['roles'].split():
        raise RuntimeError('The diagnostic fixture must remain an ordinary user')
    config, _ = api('/api/v4/config/client?format=old')
    report['self_deactivation_setting'] = config.get('EnableUserDeactivation')
    report['cleanup'] = admin.deactivate_fixture(owner, guard)
    try:
        api('/api/v4/users/me')
    except HTTPError as error:
        if error.code != 401:
            raise
        report['session_invalidated'] = True
    else:
        raise RuntimeError('Test session remains usable')
    token = ''
    try:
        api('/api/v4/users/login', {'login_id': username, 'password': password})
    except HTTPError as error:
        if error.code not in (400, 401):
            raise
        report['login_rejected'] = True
    else:
        raise RuntimeError('Inactive test account can log in')
    report['second_cleanup'] = admin.deactivate_fixture(owner, guard)
    report['status'] = 'passed'
except Exception as error:
    report.update(status='failed', error_type=type(error).__name__)
finally:
    if owner and admin:
        try:
            inactive = bool(admin.fixture(owner).get('delete_at'))
            if not inactive:
                report['recovery_cleanup'] = admin.deactivate_fixture(owner, guard)
                inactive = True
            report['active_residuals'] = [] if inactive else [owner['user_id']]
        except Exception as error:
            report['active_residuals'] = [owner['user_id']]
            report['cleanup_error_type'] = type(error).__name__
            report['status'] = 'failed'
    access.close()
    lock.close()
    (root / 'report.json').write_text(json.dumps(report, indent=2))
    (root / 'report.json').chmod(0o600)
    print(json.dumps({'report': str(root / 'report.json'), **report}))
raise SystemExit(0 if report['status'] == 'passed' else 1)
