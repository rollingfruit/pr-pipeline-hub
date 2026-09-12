"""Read-only deployment/migration comparison before a Multica rollout."""
import hashlib
import base64
import io
import json
from pathlib import Path
import sys
import tarfile
sys.path.insert(0, '/opt/pr-pipeline-ci')
from gamma_access import GammaAccess

access = GammaAccess('9253bcacca80')
try:
    access.connect()
    raw = access.remote("kubectl -n default exec deployment/multica-server -- sh -c 'tar -czf - -C /opt/ai/multica-server migrations | base64 -w0'")
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(raw))) as data:
        current = {Path(item.name).name: hashlib.sha256(data.extractfile(item).read().replace(b'\r\n', b'\n')).hexdigest()
                   for item in data if item.isfile() and item.name.endswith('.sql')}
    source = Path('/var/lib/pr-e2e') / ('opencode-final-' + sys.argv[1]) / 'source/migrations'
    wanted = {p.name: hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest() for p in source.glob('*.sql')}
    print(json.dumps({'added': sorted(wanted.keys() - current.keys()), 'removed': sorted(current.keys() - wanted.keys()),
        'changed': sorted(name for name in wanted.keys() & current.keys() if wanted[name] != current[name]),
        'current_images': access.resource('deployment', 'multica-server')['spec']['template']['spec']['containers'][0]['image']}, indent=2))
finally:
    access.close()
