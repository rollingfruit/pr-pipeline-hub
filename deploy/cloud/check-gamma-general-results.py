import hashlib
import json
from pathlib import Path
import sys
for id in ('gamma-check-20260911-172804-191bdf','gamma-check-20260911-174554-50b751'):
    root=Path('/var/lib/pr-e2e-share/runs')/id
    value=json.loads((root/'run.json').read_text())
    assert value['status']=='completed', 'Still running: '+id
    entries=value['archive_manifest']
    assert all(hashlib.sha256((root/e['path']).read_bytes()).hexdigest()==e['sha256'] for e in entries)
    print(json.dumps({'id':id,'conclusion':value['conclusion'],'stale':value.get('stale',False),
        'selected':[s['id'] for s in value['suites']], 'stages':[{k:s.get(k) for k in ('id','conclusion')} for s in value['stages']],
        'cases':[{k:t.get(k) for k in ('suite','id','status')} for t in value['test_results']],
        'rollback':value.get('rollback'),'verified_artifacts':len(entries)}))
sys.path.insert(0,'/opt/pr-pipeline-ci')
from gamma_access import GammaAccess
access=GammaAccess('a5932430eb2f')
try:
    before=json.loads((Path('/var/lib/pr-e2e/gamma-diagnostics')/id/'private/rollout-before.json').read_text())
    current=access.resource('deployment','governance')
    assert current['spec']['template']==before['spec']['template']
    for name in ('governance','mattermost','multica-server'):
        obj=access.resource('deployment',name)
        assert obj['status'].get('availableReplicas',0)==obj['spec']['replicas']
    print('RESTORED and governance/Mattermost/Multica readiness verified')
finally: access.close()
