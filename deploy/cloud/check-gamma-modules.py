"""Read-only inventory of actual dev-gamma deployment mappings."""
import json
from pathlib import Path
import sqlite3
import sys
sys.path[:0] = ['/opt/swr-push-helper','/opt/pr-pipeline-ci']
import gamma_real
from gamma_access import GammaAccess
access = GammaAccess(gamma_real.ENVIRONMENT)
deployments = {d['metadata']['name']: d for d in access.resource('deployments')['items']}
with sqlite3.connect('/opt/swr-push-helper/data/robot-ci.db') as db:
    rows = list(db.execute('select id,service_id,workload_name from environments'))
catalog = {s['id']:s for s in json.loads(Path('/opt/swr-push-helper/services.json').read_text())}
for id, sid, workload in rows:
    if not gamma_real.available(id): continue
    gamma_real.validate_selection(id, [sid])
    deploy, preferred = access.adapter.resolve_deploy_target(sid, catalog.get(sid,{}).get('image',''), workload)
    obj = deployments.get(deploy)
    if obj:
        containers = [(c['name'],c['image']) for c in obj['spec']['template']['spec']['containers']]
        container = access.adapter.pick_container(containers,image=catalog.get(sid,{}).get('image',''),preferred=preferred)
    else: container = None
    print(json.dumps({'service':sid,'environment_id':id,'deployment':deploy,'container':container,
        'mapping':'verified' if obj and sid in catalog else 'missing-workload-or-build-catalog'}))
access.close()
