"""Inspect only a dedicated acceptance account; credentials stay in memory."""
import json
from pathlib import Path
import sys
import urllib.request
import urllib.parse
sys.path.insert(0, '/opt/pr-pipeline-ci')
from gamma_access import GammaAccess

root = Path('/var/lib/pr-e2e/gamma-diagnostics') / sys.argv[1]
cfg = json.loads((root / 'private/settings.json').read_text())
boot = json.loads((root / 'private/bootstrap.json').read_text())
access = GammaAccess('a5932430eb2f')
try:
    access.connect()
    services = access.resource('services')['items']
    router = next(s for s in services if s['spec'].get('selector', {}).get('app') == 'service-router')
    base = access.forward(router['spec']['clusterIP'], 80, 0)
    multica = next(s for s in services if s['spec'].get('selector', {}).get('app') == 'multica-server')
    native = access.forward(multica['spec']['clusterIP'], 8080, 0)
    internal = json.loads((root / 'private/internal.json').read_text())['token']
    request = urllib.request.Request(base + '/api/v4/users/login', data=json.dumps({
        'login_id': cfg['TEST_ADMIN_USER'], 'password': cfg['TEST_ADMIN_PASSWORD']}).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request) as response:
        token = response.headers['Token']
    def get(route):
        with urllib.request.urlopen(urllib.request.Request(base + route, headers={'Authorization': 'Bearer ' + token})) as response:
            return json.load(response)
    channels = get('/api/v4/users/' + boot['user_id'] + '/channels')
    seen = set()
    for channel in channels:
        if channel['type'] not in ('D', 'G'): continue
        posts = get('/api/v4/channels/' + channel['id'] + '/posts')['posts'].values()
        for post in sorted(posts, key=lambda p: p['create_at']):
            print(json.dumps({'channel': channel['id'], 'id': post['id'], 'user': post['user_id'],
                'message': post['message'][:220], 'props': {k: v for k, v in post.get('props', {}).items()
                if k in ('source_post_id', 'agent_run_id', 'agent_run_companion_kind', 'agent_task_id', 'trace_id')}}, ensure_ascii=False))
            run_id = post.get('props', {}).get('agent_run_id', '')
            if run_id and not run_id.startswith('opening-ack') and run_id not in seen:
                seen.add(run_id)
                query = urllib.parse.urlencode({'user_id': boot.get('CONTROL_USER_ID') or boot['user_id'], 'user_name': boot['username']})
                run = get('/v1/agent/agent-runs/' + run_id + '?' + query)
                print(json.dumps({'run': run_id, 'status': run.get('status'), 'task': run.get('task_id'),
                    'events': run.get('events'), 'failure': run.get('failure'), 'final_response': run.get('final_response')}, ensure_ascii=False))
                with urllib.request.urlopen(urllib.request.Request(native + '/v1/agent/jobs/' + run['task_id'],
                        headers={'X-Auth-Token': internal})) as response:
                    job = json.load(response)
                print(json.dumps({'native_job': job}, ensure_ascii=False))
finally:
    access.close()
