"""Operator CLI for the authenticated single Gamma queue; never runs tests directly."""
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['diagnostic', 'stability', 'status'])
parser.add_argument('id')
args = parser.parse_args()
token = Path('/etc/pr-e2e/secrets/worker-token').read_text().strip()
payload = None
route = '/api/runs/' + args.id
if args.action != 'status':
    route = '/internal/gamma'
    payload = {'submission_id': args.id, 'environment_id': 'a5932430eb2f',
               'mode': 'test' if args.action == 'diagnostic' else 'stability',
               'suite_ids': ['E01', 'E02', 'E03', 'E04', 'E05', 'E06'],
               'requested_by': 'operator-p0-acceptance'}
    if args.action == 'stability':
        payload['rounds'] = 10
request = Request('http://127.0.0.1:8792' + route,
                  data=json.dumps(payload).encode() if payload else None,
                  headers={'Content-Type': 'application/json', 'X-Worker-Token': token})
with urlopen(request, timeout=30) as response:
    result = json.load(response)
if args.action == 'status':
    result = {k: result.get(k) for k in ('id', 'status', 'summary', 'conclusion', 'current_round',
               'active_run_id', 'completed_rounds', 'statistics', 'cleanup', 'environment_health', 'rounds', 'stages')}
    if result.get('rounds'):
        result['rounds'] = [{k: row.get(k) for k in ('index', 'run_id', 'first_pass', 'conclusion',
                             'failure_kind', 'archive_verified', 'summary', 'cleanup')} for row in result['rounds']]
print(json.dumps(result, ensure_ascii=False))
