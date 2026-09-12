"""Read-only readiness and cleanup capability probe; never changes the cluster."""
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

sys.path.insert(0, '/opt/pr-pipeline-ci')
from gamma_access import GammaAccess
access = GammaAccess('a5932430eb2f')
try:
    access.connect()
    services = access.resource('services')['items']
    router = next(s for s in services if s['spec'].get('selector', {}).get('app') == 'service-router')
    base = access.forward(router['spec']['clusterIP'], 80, 0)
    with urlopen(base + '/api/v4/config/client?format=old', timeout=20) as response:
        config = json.load(response)
    print(json.dumps({'self_deactivation': config.get('EnableUserDeactivation'), 'shape': list(config)[:10]}))
    settings = Path('/var/lib/pr-e2e/gamma-diagnostics/gamma-check-20260911-205917-64cccb/private/settings.json')
    if settings.exists():
        fixture = json.loads(settings.read_text())
        login = Request(base + '/api/v4/users/login', data=json.dumps({
            'login_id': fixture['TEST_ADMIN_USER'], 'password': fixture['TEST_ADMIN_PASSWORD']}).encode(),
            headers={'Content-Type': 'application/json'})
        with urlopen(login, timeout=20) as response:
            user = json.load(response)
            token = response.headers['Token']
        print(json.dumps({'test_account_roles': user.get('roles')}))
        with urlopen(Request(base + '/api/v4/config/client?format=old',
                             headers={'Authorization': 'Bearer ' + token}), timeout=20) as response:
            config = json.load(response)
        print(json.dumps({'authenticated_self_deactivation': config.get('EnableUserDeactivation')}))
        with urlopen(Request(base + '/api/v4/users/logout', data=b'{}',
                             headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}), timeout=20):
            pass
    from gamma_readiness import wait_for_deployments
    names = {d['metadata']['name'] for d in access.resource('deployments')['items']}
    images = wait_for_deployments(access, names)
    print(json.dumps({'ready_deployments': len(images)}))
finally:
    access.close()
