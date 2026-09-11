"""Hash-guarded, idle-only additive deployment of the Robot Gamma bridge."""
import datetime
import hashlib
import json
from pathlib import Path
import py_compile
import shutil
import subprocess
import os
import time

root = Path('/opt/swr-push-helper')
target = root / 'server.py'
expected = '2cfbcffe2fefb8be4390623105cac83bb612d1107f3121d83565610cc7199294'
if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
    raise SystemExit('Server changed concurrently; fetch and reapply the additive patch')
pid = int(subprocess.check_output(['systemctl', 'show', 'swr-push-helper', '-p', 'MainPID', '--value']))
uptime = float(Path('/proc/uptime').read_text().split()[0])
ticks = int(Path(f'/proc/{pid}/stat').read_text().split()[21])
started = time.time() - uptime + ticks / os.sysconf('SC_CLK_TCK')
for file in (root / 'logs').glob('job-*.json'):
    job = json.loads(file.read_text())
    # Robot CI does not restore in-memory jobs at startup; old fixtures are not live jobs.
    if job.get('status') in ('running', 'queued') and file.stat().st_mtime >= started:
        raise SystemExit('Active job: ' + job['id'] + '; deployment deferred')
source = Path('/opt/pr-pipeline-ci/gamma-patched-server.py')
py_compile.compile(str(source), doraise=True)
backup = Path('/var/backups/pr-e2e') / ('real-gamma-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True)
shutil.copy2(target, backup / 'server.py')
shutil.copy2(root / 'gamma_real.py', backup / 'gamma_real.py')
shutil.copy2(source, target)
subprocess.run(['systemctl', 'restart', 'swr-push-helper'], check=True)
print('DEPLOYED', backup)
