import json
from pathlib import Path
from urllib.request import Request, urlopen

run_id = 'admin-check-20260912-114559-60e827'
token = Path('/etc/pr-e2e/secrets/worker-token').read_text().strip()
with urlopen(Request('http://127.0.0.1:8792/api/runs/' + run_id,
                     headers={'X-Worker-Token': token}), timeout=15) as response:
    report = json.load(response)
print(json.dumps({k: report.get(k) for k in ('id', 'status', 'conclusion', 'diagnostic', 'full_acceptance')}))
