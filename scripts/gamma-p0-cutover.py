"""Explicit, quiescent P0 deployment. Keeps credentials and backups private."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from urllib.request import Request, urlopen

STAGE = Path('/opt/gamma-p0-validation')
CI = Path('/opt/pr-pipeline-ci')
HUB = Path('/opt/pr-e2e-share')
ROBOTS = [Path('/opt/swr-push-helper'), Path('/opt/swr-push-helper-18889')]
token = Path('/etc/pr-e2e/secrets/worker-token').read_text().strip()


def command(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def runs():
    with urlopen(Request('http://127.0.0.1:8792/api/runs', headers={'X-Worker-Token': token}), timeout=20) as response:
        value = json.load(response)
    return value.get('runs', []) if isinstance(value, dict) else value


def quiet():
    if any(r['status'] in ('running', 'interrupted') for r in runs()):
        raise RuntimeError('Hub has active or unreconciled execution')
    for robot in ROBOTS:
        for path in (robot / 'logs').glob('job-*.json'):
            value = json.loads(path.read_text())
            if re.fullmatch('[a-f0-9]{8,32}', str(value.get('id', ''))) and value.get('status') in ('running', 'queued'):
                raise RuntimeError('Robot CI has active build: ' + value['id'])


def install(source, target, mode=0o644):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.p0-new')
    shutil.copyfile(source, temporary)
    os.chown(temporary, 0, 0)
    temporary.chmod(mode)
    temporary.replace(target)


quiet()
backup = Path('/var/backups/pr-gamma-p0') / time.strftime('%Y%m%d-%H%M%S')
backup.mkdir(parents=True, mode=0o700)
backup.parent.chmod(0o700)
for root in [CI, HUB, *ROBOTS]:
    folder = backup / root.name
    folder.mkdir(mode=0o700)
    for pattern in ('*.py', '*.json'):
        for path in root.glob(pattern):
            shutil.copy2(path, folder / path.name)
    if (root / 'data/robot-ci.db').exists():
        with sqlite3.connect(root / 'data/robot-ci.db') as source, sqlite3.connect(folder / 'robot-ci.db') as target:
            source.backup(target)
for path in (Path('/etc/pr-pipeline-control.env'), Path('/etc/pr-e2e/config.toml')):
    shutil.copy2(path, backup / path.name)
from psycopg.conninfo import conninfo_to_dict
dsn = next(line.split('=', 1)[1].strip().strip('"').strip("'") for line in Path('/etc/pr-pipeline-control.env').read_text().splitlines() if line.startswith('PIPELINE_DATABASE_URL='))
info = conninfo_to_dict(dsn)
with (backup / 'queue.sql').open('wb') as output:
    command(['docker', 'exec', '-e', 'PGPASSWORD=' + info.get('password', ''), 'pr-pipeline-postgres',
             'pg_dump', '-U', info['user'], info['dbname']], stdout=output)
print('BACKUP=' + str(backup), flush=True)

services = ['swr-push-helper', 'swr-push-helper-18889', 'pr-ci@worker']
for service in services:
    command(['systemctl', 'stop', service])
quiet()
command(['systemctl', 'stop', 'pr-pipeline-control'])

for name in ('control_api.py', 'control_store.py', 'gamma_queue.py'):
    install(STAGE / 'hub' / name, HUB / name)
install(STAGE / 'hub/cloud_entry.py', CI / 'cloud_entry.py')
for source in (STAGE / 'hub').glob('gamma_*.py'):
    install(source, CI / source.name)
install(STAGE / 'hub/e2e_execution_graph.py', CI / 'e2e_execution_graph.py')
install(STAGE / 'hub/control_worker.py', CI / 'control_worker.py')
for source in (STAGE / 'stack').rglob('*'):
    if source.is_file() and 'node_modules' not in source.parts:
        install(source, CI / 'stack' / source.relative_to(STAGE / 'stack'))
for index, robot in enumerate(ROBOTS):
    install(STAGE / ('gamma-main-server.py' if index == 0 else 'gamma-preview-server.py'), robot / 'server.py')
    install(STAGE / 'robot/gamma_real.py', robot / 'gamma_real.py')

# The privileged helper imports these modules. Do not trust group/world-writable code.
for root in [CI, HUB, *ROBOTS]:
    os.chown(root, 0, 0)
    root.chmod(0o755)
    for path in root.glob('*.py'):
        os.chown(path, 0, 0)
        path.chmod(0o644)
    cache = root / '__pycache__'
    if cache.exists():
        os.chown(cache, 0, 0)
        cache.chmod(0o755)
        for path in cache.glob('*.pyc'):
            os.chown(path, 0, 0)
            path.chmod(0o644)
account = pwd.getpwnam('pr-e2e')
for path in [Path('/var/lib/pr-gamma-executor'), Path('/var/lib/pr-gamma-executor/diagnostics')]:
    path.mkdir(exist_ok=True, mode=0o750)
    os.chown(path, 0, account.pw_gid)
    path.chmod(0o750)
install(STAGE / 'pr-gamma-execute', Path('/usr/local/sbin/pr-gamma-execute'), 0o755)
sudoers = Path('/etc/sudoers.d/pr-gamma-execute')
sudoers.write_text('pr-e2e ALL=(root) NOPASSWD: /usr/local/sbin/pr-gamma-execute gamma-*\n')
sudoers.chmod(0o440)
command(['visudo', '-cf', str(sudoers)])
command(['/usr/local/bin/python3.11', '-m', 'py_compile', *[str(p) for p in CI.glob('*.py')],
         str(HUB / 'control_api.py'), *[str(r / 'server.py') for r in ROBOTS]])
command(['systemctl', 'start', 'pr-pipeline-control'])
for _ in range(30):
    try:
        runs()
        break
    except Exception:
        time.sleep(1)
else:
    raise RuntimeError('Control plane failed readiness; worker remains stopped')
for service in services:
    command(['systemctl', 'start', service])
print(json.dumps({'cutover': 'started', 'backup': str(backup)}))
