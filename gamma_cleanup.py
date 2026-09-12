"""Clean only resources attributable to this Gamma execution; never hide failures."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def residual_processes(root, uid):
    found = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            if proc.stat().st_uid != uid:
                continue
            env = dict(part.split(b'=', 1) for part in (proc / 'environ').read_bytes().split(b'\0') if b'=' in part)
            home = Path(env.get(b'HOME', b'/').decode()).resolve()
            if home.is_relative_to(root):
                found.append(int(proc.name))
        except (FileNotFoundError, ProcessLookupError):
            continue
    return found


def _cleanup(root, env, access, guard=None):
    root = Path(root).resolve()
    settings = root / 'frozen-settings.json'
    cfg = json.loads((settings if settings.exists() else root / 'private/settings.json').read_text())
    if not cfg['TEST_ADMIN_USER'].startswith('gamma-e2e-') or not root.name.startswith('gamma-check-'):
        raise RuntimeError('Cleanup ownership mismatch')
    from gamma_admin import MattermostAdmin
    from gamma_lease import check
    check_lease = guard or check
    owner_path = root / 'ownership.json'
    if owner_path.is_symlink() or owner_path.stat().st_uid != 0 or owner_path.stat().st_mode & 0o022:
        raise RuntimeError('Root-owned fixture ledger is required for administrative cleanup')
    owner = json.loads(owner_path.read_text())
    if (owner.get('run_id') != root.name or owner.get('username') != cfg['TEST_ADMIN_USER']
            or owner.get('email') != cfg['TEST_ADMIN_EMAIL']
            or owner.get('daemon_id') != cfg.get('DAEMON_ID')
            or owner.get('workspace_id') != cfg.get('WORKSPACE_ID')):
        raise RuntimeError('Fixture ledger does not match this execution')
    admin = MattermostAdmin(access)
    admin.fixture(owner)
    result = {'status': 'running', 'created': {}, 'removed': [], 'retained': [],
              'active_residuals': [{'kind': 'business_inventory_unverified'}], 'errors': []}
    base = env['E2E_APP_URL']
    token = ''
    def api(route, data=None, method=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        request = Request(base + route, data=None if data is None else json.dumps(data).encode(),
                          headers=headers, method=method)
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            return (json.loads(raw) if raw else {}), response.headers
    try:
        user, headers = api('/api/v4/users/login', {'login_id': cfg['TEST_ADMIN_USER'], 'password': cfg['TEST_ADMIN_PASSWORD']})
        token = headers['Token']
        boot = json.loads((root / 'private/bootstrap.json').read_text())
        if user['id'] != boot['user_id'] or user['id'] != owner['user_id']:
            raise RuntimeError('Cleanup account differs from bootstrap owner')
        result['created']['test_accounts'] = 1
        result['active_residuals'] = [{'kind': 'test_account', 'id': user['id']},
                                      {'kind': 'bot_inventory_unverified'}]
        identity = {'user_id': cfg.get('CONTROL_USER_ID') or user['id'], 'user_name': user['username']}
        route = '/v1/agent/managed-platforms'
        managed, _ = api(route + '?' + urlencode(identity))
        bots = [a for a in managed.get('agents', []) if a.get('managed_daemon_id') == cfg.get('DAEMON_ID')
                and a.get('managed_workspace_id') == cfg.get('WORKSPACE_ID')]
        result['created']['bots'] = len(bots)
        result['active_residuals'] = [{'kind': 'test_account', 'id': user['id']}] + [
            {'kind': 'bot_binding', 'id': b['bot_id']} for b in bots]
        for bot in bots:
            bot_id = bot['bot_id']
            check_lease()
            api(route + '/agents/delete', {'bot_id': bot_id, **identity})
            result['removed'].append({'kind': 'bot_binding', 'id': bot_id})
        after, _ = api(route + '?' + urlencode(identity))
        remaining = [a['bot_id'] for a in after.get('agents', []) if a.get('managed_daemon_id') == cfg.get('DAEMON_ID')]
        result['active_residuals'] = [{'kind': 'test_account', 'id': user['id']}] + [
            {'kind': 'bot_binding', 'id': i} for i in remaining]
        # Channel transcripts are intentional evidence, not runnable resources.
        channels, _ = api('/api/v4/users/' + user['id'] + '/channels')
        result['retained'].extend({'kind': 'transcript', 'id': c['id']} for c in channels)
        for attempt in range(2):
            try:
                receipt = admin.deactivate_fixture(owner, check_lease)
                break
            except (RuntimeError, OSError):
                if attempt:
                    raise
                time.sleep(1)
        try:
            api('/api/v4/users/me')
        except HTTPError as error:
            if error.code != 401:
                raise
        else:
            raise RuntimeError('Test session remains usable after account deactivation')
        receipt['test_session_invalidated'] = True
        result['active_residuals'] = [r for r in result['active_residuals'] if r['kind'] != 'test_account']
        result['removed'].append(receipt)
    except Exception as error:
        result['errors'].append({'phase': 'business_cleanup', 'type': type(error).__name__,
                                 'status': getattr(error, 'code', None)})
    profile = cfg.get('LOCAL_DAEMON_PROFILE')
    if profile:
        if not profile.startswith('pr-e2e-'):
            raise RuntimeError('Refusing non-test Daemon cleanup')
        daemon_env = {**env, 'HOME': str(root / 'state/daemon-home')}
        for attempt in range(2):
            stop = subprocess.run(['/usr/sbin/runuser', '-u', 'pr-e2e', '--', str(root / 'bin/multica'),
                                   'daemon', 'stop', '--profile', profile], env=daemon_env,
                                  capture_output=True, timeout=45)
            health = subprocess.run(['/usr/sbin/runuser', '-u', 'pr-e2e', '--', str(root / 'bin/multica'),
                                     'daemon', 'status', '--profile', profile, '--output', 'json'], env=daemon_env,
                                    capture_output=True, timeout=15)
            try:
                stopped = health.returncode == 0 and json.loads(health.stdout).get('status') == 'stopped'
            except ValueError:
                stopped = False
            if stopped:
                result['removed'].append({'kind': 'daemon_stopped', 'id': cfg.get('DAEMON_ID')})
                break
            if attempt == 1:
                result['active_residuals'].append({'kind': 'daemon', 'id': cfg.get('DAEMON_ID')})
    result['retained'].append({'kind': 'shared_workspace_record', 'id': cfg.get('WORKSPACE_ID'),
                              'scope': 'only this run owns its test account, bots and daemon'})
    result['status'] = 'passed' if not result['errors'] and not result['active_residuals'] else 'failed'
    return result


def stop_owned_processes(root):
    import pwd
    uid = pwd.getpwnam('pr-e2e').pw_uid
    for pid in residual_processes(root, uid):
        descriptor = None
        try:
            descriptor = os.pidfd_open(pid)
            # Recheck after opening the descriptor so a reused PID cannot be signalled.
            if pid in residual_processes(root, uid):
                signal.pidfd_send_signal(descriptor, signal.SIGTERM)
        except ProcessLookupError:
            pass
        finally:
            if descriptor is not None:
                os.close(descriptor)
    deadline = time.monotonic() + 15
    while residual_processes(root, uid) and time.monotonic() < deadline:
        time.sleep(1)
    return [{'kind': 'process', 'pid': pid} for pid in residual_processes(root, uid)]


def cleanup(root, env, access, guard=None):
    root = Path(root).resolve()
    if root.parent != Path('/var/lib/pr-gamma-executor/diagnostics') or not root.name.startswith('gamma-check-'):
        raise RuntimeError('Unexpected Gamma execution directory')
    try:
        result = _cleanup(root, env, access, guard) if guard else _cleanup(root, env, access)
    except Exception as error:
        result = {'status': 'failed', 'created': {}, 'removed': [], 'retained': [],
                  'active_residuals': [{'kind': 'business_inventory_unverified'}],
                  'errors': [{'phase': 'cleanup', 'type': type(error).__name__}]}
    # Remote authorization or inventory errors must not leave this run's local processes running.
    try:
        result['active_residuals'].extend(stop_owned_processes(root))
    except Exception as error:
        result['errors'].append({'phase': 'process_cleanup', 'type': type(error).__name__})
        result['active_residuals'].append({'kind': 'process_inventory_unverified'})
    if not result['errors'] and not result['active_residuals']:
        try:
            result['retained'].extend(verify_runtime_inactive(root, access))
        except Exception as error:
            result['errors'].append({'phase': 'runtime_inventory', 'type': type(error).__name__})
            result['active_residuals'].append({'kind': 'runtime_inventory_unverified'})
    if result['errors'] or result['active_residuals']:
        result['status'] = 'failed'
    return result


def verify_runtime_inactive(root, access):
    cfg = json.loads((root / 'frozen-settings.json').read_text())
    services = access.resource('services')['items']
    service = next(s for s in services if s['spec'].get('selector', {}).get('app') == 'multica-server')
    base = access.forward(service['spec']['clusterIP'], 8080, 0)
    token = json.loads((root / 'private/internal.json').read_text())['token']
    query = urlencode({'workspace_id': cfg['WORKSPACE_ID'], 'team_id': 'hw', 'user_id': cfg.get('CONTROL_USER_ID')})
    for attempt in range(25):
        with urlopen(Request(base + '/v1/agent/im-integrations/runtimes?' + query,
                             headers={'X-Auth-Token': token}), timeout=15) as response:
            payload = json.load(response)
        rows = payload if isinstance(payload, list) else payload['runtimes']
        owned = [r for r in rows if r.get('daemon_id') == cfg['DAEMON_ID']]
        if all(r.get('workspace_id') == cfg['WORKSPACE_ID'] and r.get('status') == 'offline' for r in owned):
            return [{'kind': 'offline_runtime_record', 'id': r['id'], 'status': r['status']} for r in owned]
        if attempt < 24:
            time.sleep(5)
    raise RuntimeError('Server still reports an active or unknown dedicated Runtime')
