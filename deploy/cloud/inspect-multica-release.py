"""Read deployed image identity without exposing container configuration."""
import json
import sys
sys.path.insert(0, '/opt/pr-pipeline-ci')
from gamma_access import GammaAccess

access = GammaAccess('9253bcacca80')
try:
    access.connect()
    pods = access.resource('pods')['items']
    for pod in pods:
        if pod.get('metadata', {}).get('labels', {}).get('app') != 'multica-server': continue
        print(json.dumps({'pod': pod['metadata']['name'], 'node': pod['spec']['nodeName'],
            'requested_images': [c['image'] for c in pod['spec']['containers']],
            'containers': pod['status'].get('containerStatuses')}, ensure_ascii=False))
    access.environment['nodes'] = ['172.31.9.233']
    raw = access.remote('crictl images -o json')
    for item in json.loads(raw).get('images', []):
        if any('/multica-server' in tag for tag in item.get('repoTags', []) + item.get('repoDigests', [])):
            info = json.loads(access.remote('crictl inspecti ' + item['id']))
            spec = info.get('info', {}).get('imageSpec', {})
            print(json.dumps({'image': item, 'labels': spec.get('config', {}).get('Labels', {})}, ensure_ascii=False))
finally:
    access.close()
