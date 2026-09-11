"""Install the tested additive guard without overwriting concurrent Robot CI edits."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

root = Path('/opt/swr-push-helper')
stage = Path('/var/tmp/pipeline-gamma-guard')
server = root / 'server.py'
expected = '36a4da54b954f906ccf018c485a214f68cad804ab026b6bbd23d909cdc088db6'
if hashlib.sha256(server.read_bytes()).hexdigest() != expected:
    raise SystemExit('Robot CI changed after inspection; refusing to overwrite')
cfg = json.loads((root / 'config.json').read_text())
markers = Path(cfg['workspace_root']) / '.robot-ci-cache/live-jobs'
for path in markers.glob('*'):
    if not path.is_file() or path.name.endswith('.tmp'):
        continue
    record = json.loads(path.read_text())
    if record.get('pid') and Path('/proc/' + str(record['pid'])).exists():
        raise SystemExit('Active build marker: ' + path.name)
for path in (root / 'logs').glob('job-*.json'):
    if not re.fullmatch(r'job-[a-f0-9]{8,32}\.json', path.name):
        continue
    record = json.loads(path.read_text())
    if record.get('status') in {'running', 'queued'}:
        raise SystemExit('Unfinished Robot CI build: ' + path.name)
compile((stage / 'server.py').read_text(), 'server.py', 'exec')
backup = Path('/var/backups/pr-e2e') / ('gamma-guard-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
backup.mkdir(parents=True, mode=0o700)
targets = {server: stage / 'server.py'}
for directory in ('/opt/pr-pipeline-ci', '/opt/pr-e2e-share'):
    targets[Path(directory) / 'static/branch-editor.html'] = stage / 'static/branch-editor.html'
for target in targets:
    saved = backup / str(target).lstrip('/')
    saved.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, saved)
try:
    for target, source in targets.items():
        target.write_bytes(source.read_bytes())
    subprocess.run(['systemctl', 'restart', 'swr-push-helper'], check=True)
    subprocess.run(['systemctl', 'restart', 'pr-pipeline-control'], check=True)
    import urllib.request
    for attempt in range(30):
        try:
            with urllib.request.urlopen('http://127.0.0.1:18082/api/auth/me', timeout=2) as response:
                if json.load(response).get('user') is not None:
                    raise RuntimeError('Anonymous request unexpectedly authenticated')
            break
        except OSError:
            time.sleep(1)
    else:
        raise RuntimeError('Robot CI did not become ready')
except Exception:
    for target in targets:
        target.write_bytes((backup / str(target).lstrip('/')).read_bytes())
    subprocess.run(['systemctl', 'restart', 'swr-push-helper'], check=False)
    raise
print('Guard and single-branch editor installed; backup:', backup)
