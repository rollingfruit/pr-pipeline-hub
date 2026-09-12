"""Check deployment quiescence without printing credentials or changing services."""
import json
from pathlib import Path
from urllib.request import Request, urlopen

token = Path('/etc/pr-e2e/secrets/worker-token').read_text().strip()
with urlopen(Request('http://127.0.0.1:8792/api/runs', headers={'X-Worker-Token': token}), timeout=15) as response:
    runs = json.load(response)
if isinstance(runs, dict):
    runs = runs['runs']
print(json.dumps({'hub_active': [{k: r.get(k) for k in ('id', 'status', 'title')}
                              for r in runs if r.get('status') in ('running', 'interrupted')]}))
for name in ('swr-push-helper', 'swr-push-helper-18889'):
    root = Path('/opt') / name
    active = []
    for file in (root / 'logs').glob('job-*.json'):
        try:
            row = json.loads(file.read_text())
            if row.get('status') in ('running', 'queued') and 'optional_steps' in row:
                active.append({k: row.get(k) for k in ('id', 'status', 'stage')})
        except ValueError:
            continue
    print(json.dumps({'service': name, 'active': active}))
