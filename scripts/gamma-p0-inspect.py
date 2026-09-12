"""Inspect one owned diagnostic, printing only status and resource identifiers."""
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen
sys.path.insert(0, '/opt/pr-pipeline-ci')
from gamma_access import GammaAccess
root = Path('/var/lib/pr-gamma-executor/diagnostics') / sys.argv[1]
if not root.name.startswith('gamma-check-'):
    raise SystemExit('Diagnostic ID required')
cfg = json.loads((root / 'private/settings.json').read_text())
access = GammaAccess('a5932430eb2f')
try:
    access.connect()
    router = next(s for s in access.resource('services')['items'] if s['spec'].get('selector', {}).get('app') == 'service-router')
    base = access.forward(router['spec']['clusterIP'], 80, 0)
    with urlopen(Request(base + '/api/v4/users/login', data=json.dumps({'login_id': cfg['TEST_ADMIN_USER'], 'password': cfg['TEST_ADMIN_PASSWORD']}).encode(), headers={'Content-Type': 'application/json'}), timeout=20) as response:
        user = json.load(response)
        token = response.headers['Token']
    query = urlencode({'user_id': cfg.get('CONTROL_USER_ID') or user['id'], 'user_name': user['username']})
    with urlopen(Request(base + '/v1/agent/managed-platforms?' + query, headers={'Authorization': 'Bearer ' + token}), timeout=20) as response:
        data = json.load(response)
    print(json.dumps({'keys': list(data), 'agents': [{k: a.get(k) for k in ('bot_id', 'managed_daemon_id', 'managed_workspace_id', 'daemon_id', 'workspace_id', 'owner_user_id')} for a in data.get('agents', [])], 'expected_daemon': cfg.get('DAEMON_ID'), 'expected_workspace': cfg.get('WORKSPACE_ID')}))
    from gamma_cleanup import residual_processes
    import pwd
    print(json.dumps({'owned_process_cgroups': [{'pid': p, 'cgroup': Path(f'/proc/{p}/cgroup').read_text()} for p in residual_processes(root.resolve(), pwd.getpwnam('pr-e2e').pw_uid)]}))
finally:
    access.close()
