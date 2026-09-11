"""Resolve repository identities and register the allowlist. Never backfill PRs."""
import json
import os
from pathlib import Path
from control_client import rpc
from pr_pipeline_hub import PipelineHub, atomic_json
from review_policy import REPOSITORIES

os.environ['PIPELINE_NO_WORKER'] = '1'
root = Path(__file__).resolve().parent
hub = PipelineHub(root / '.runtime/registry-tool')
report = []
seen = set()
for name in REPOSITORIES:
    repository = hub._gh_json(['api', 'repos/rollingfruit/'+name])
    identity, canonical = repository['id'], repository['full_name']
    if identity in seen:
        continue
    seen.add(identity)
    rpc('/internal/repositories', {'id':identity,'name':canonical})
    hooks = hub._gh_json(['api', f'repos/{canonical}/hooks'])
    local = root.parent / 'mattermost-microservice' / name
    report.append({'id':identity,'name':canonical,'private':repository['private'],
        'admin':repository.get('permissions',{}).get('admin',False), 'local_source_exists':local.is_dir(),
        'hook_ids':[h['id'] for h in hooks if h.get('config',{}).get('url')=='http://119.8.233.58:8080/webhooks/github'],
        'build_mapping':'requires_shared_runtime_mapping' if name=='public-service' else 'requires_compose_mapping' if name=='observability' else 'existing_service',
        'e2e_verified':False})
    print(json.dumps(report[-1]))
atomic_json(root / '.runtime/repositories.json', report)
print(f'Registered {len(report)} canonical identities. No Webhooks enabled, no PR scans performed.')
