"""Record real GitHub delivery receipts, without exposing payloads or signatures."""
import json
import os
from pathlib import Path
from pr_pipeline_hub import PipelineHub, atomic_json

os.environ['PIPELINE_NO_WORKER']='1'
root=Path(__file__).resolve().parent
hub=PipelineHub(root/'.runtime/registry-tool')
records=json.loads((root/'.runtime/webhooks.json').read_text())
for record in records:
    deliveries=hub._gh_json(['api',f"repos/{record['repo']}/hooks/{record['hook_id']}/deliveries?per_page=10"])
    record['receipts']=[{key:d.get(key) for key in ('id','guid','event','action','status_code','delivered_at')} for d in deliveries]
    print(json.dumps({'repo':record['repo'],'receipts':record['receipts']}),flush=True)
atomic_json(root/'.runtime/webhooks.json',records)
if not all(any(d['status_code']==200 for d in r['receipts']) for r in records):
    raise SystemExit('Some hooks have not yet delivered successfully')
print('All 12 hooks have real HTTP 200 delivery receipts.')
