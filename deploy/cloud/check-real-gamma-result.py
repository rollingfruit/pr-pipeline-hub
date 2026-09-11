"""Read-only acceptance checks for the delivered build and evidence archives."""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, '/opt/pr-pipeline-ci')
from gamma_access import GammaAccess

for id in ('gamma-check-20260911-163733-5093c8', 'gamma-check-20260911-164807-d0820a'):
    root = Path('/var/lib/pr-e2e-share/runs') / id
    result = json.loads((root / 'run.json').read_text())
    entries = result['archive_manifest']
    valid = all(hashlib.sha256((root / e['path']).read_bytes()).hexdigest() == e['sha256'] for e in entries)
    assert valid
    print(json.dumps({'id': id, 'conclusion': result['conclusion'], 'rollback': result.get('rollback'),
        'stages': [{k:s.get(k) for k in ('id', 'conclusion')} for s in result['stages']],
        'verified_artifacts': len(entries), 'image': result['build_result']['image']}))
access = GammaAccess('a5932430eb2f')
for name in ('governance', 'mattermost', 'multica-server'):
    obj = access.resource('deployment', name)
    images = [c['image'] for c in obj['spec']['template']['spec']['containers']]
    assert obj['status'].get('availableReplicas', 0) == obj['spec']['replicas']
    if name == 'governance':
        assert result['build_result']['image'] in images
    print(json.dumps({'deployment': name, 'available': obj['status'].get('availableReplicas'), 'images': images}))
access.close()
