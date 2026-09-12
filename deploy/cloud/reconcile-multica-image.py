"""Restore desired Multica image to the verified, currently serving digest."""
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, '/opt/pr-pipeline-ci')
from gamma_access import GammaAccess
from gamma_rollout import GammaRollout

image = 'swr.cn-southwest-2.myhuaweicloud.com/public_ai/multica-server@sha256:a4859df6c18a0bc08b72040d447b356514b477e3ebcb1e2167b298d1d193a25b'
commit = '4e3e8c5f74f6cdb92f7220685cb8fea9a7cd553a'
root = Path('/var/lib/pr-e2e/gamma-maintenance/20260911-opencode')
root.mkdir(parents=True, exist_ok=True, mode=0o700)
lock = Path('/var/lib/pr-e2e/gamma-diagnostics/dev-gamma.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
docker = ['docker', '-H', 'unix:///run/pr-e2e/docker.sock']
data = json.loads(subprocess.check_output(docker + ['image', 'inspect', image]))[0]
if data['Config']['Labels']['org.opencontainers.image.revision'] != commit:
    raise RuntimeError('Backup image revision mismatch')
archive = root / 'multica-before.tar'
if not archive.exists():
    subprocess.run(docker + ['save', '-o', str(archive), image], check=True)
    archive.chmod(0o600)
access = GammaAccess('9253bcacca80')
try:
    access.connect()
    manifest = {'pinned_image': image, 'result': {'service_id': 'multica-server', 'commit_sha': commit, 'ok': True}}
    rollout = GammaRollout(access, manifest, root)
    changes = rollout.prepare()
    if changes['before'] not in (image, 'swr.cn-southwest-2.myhuaweicloud.com/public_ai/multica-server:202609091028_aa7f77f'):
        raise RuntimeError('Another operator changed the desired image; refusing reconciliation')
    print(json.dumps(changes), flush=True)
    rollout.apply()
    result = {'kind': 'repair-desired-image-to-serving-digest', 'changes': changes,
              'backup_sha256': hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest(), 'status': 'ready'}
    (root / 'reconciliation.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)
finally:
    access.close()
    lock.close()
