"""Additive deployment; refuse concurrent edits or active Robot CI builds."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request

root = Path('/opt/swr-push-helper')
files = {'server.py': 'beada12fcb7e0a294aef73473cb4c0fbdc3ee4df5a8a86aba72ebe882e3d4909',
         'web/app.js': 'ce3ff3e5f727b1794c5ea57e85747b6e17c86872328e84fe607015c4a16185ec'}
for name, expected in files.items():
    if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
        raise SystemExit('Concurrent code change: ' + name)
for p in (root / 'logs').glob('job-*.json'):
    if re.fullmatch(r'job-[a-f0-9]{12}\.json', p.name):
        if json.loads(p.read_text()).get('status') in {'running', 'queued'}:
            raise SystemExit('Active job: ' + p.name)
cfg = json.loads((root / 'config.json').read_text())
for p in (Path(cfg['workspace_root']) / '.robot-ci-cache/live-jobs').glob('*.json'):
    pid = json.loads(p.read_text()).get('pid')
    if pid and Path('/proc/' + str(pid)).exists():
        raise SystemExit('Active build marker: ' + p.name)
compile(Path('/var/tmp/server.py').read_text(), 'server.py', 'exec')
backup = Path('/var/backups/pr-e2e') / ('build-preflight-' + time.strftime('%Y%m%d-%H%M%S'))
backup.mkdir(mode=0o700)
for name in files:
    target = backup / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / name, target)
try:
    for name in files:
        shutil.copy2(Path('/var/tmp') / Path(name).name, root / name)
    subprocess.run(['systemctl', 'restart', 'swr-push-helper'], check=True)
    for attempt in range(20):
        try:
            with urllib.request.urlopen('http://127.0.0.1:18082/api/auth/me', timeout=2) as response:
                assert response.status == 200
            break
        except OSError:
            time.sleep(1)
    else:
        raise RuntimeError('Robot CI did not become ready')
except Exception:
    for name in files:
        shutil.copy2(backup / name, root / name)
    subprocess.run(['systemctl', 'restart', 'swr-push-helper'], check=False)
    raise
print('Deployed; backup:', backup)
