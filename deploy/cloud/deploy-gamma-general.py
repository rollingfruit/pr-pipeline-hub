"""Deploy additive multi-module Gamma changes after concurrency/hash checks."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import time

root = Path('/opt/swr-push-helper')
stage = Path('/opt/pr-pipeline-ci/gamma-general-stage')
targets = {
    'server.py': (root/'server.py', '1c8ccaf18c2d8847b4134a4d0137cf4086004dd593c6f0a53f01c8f23a2713d5'),
    'app.js': (root/'web/app.js', '68a42902fb1acf3a693298a6d2b9cb09a82a744ad2bfd810959314496da66254'),
    'gamma_real.py': (root/'gamma_real.py', '4814f7f843f4676e23d60b900b781c0a726191930d96e3270debb40b3f7e8aa4'),
    'gamma_e2e.py': (root/'gamma_e2e.py', 'c4eeb52dc55ce211328d306b22cd428eb98757d56c7795830254f2e9e2f8765c'),
    'gamma_acceptance.py': (Path('/opt/pr-pipeline-ci/gamma_acceptance.py'), '3e50a0ac6afacfedc7d8229ae41a2bdfa58bb0f160a0f08cf9f47d7be611138b'),
}
for name, (path, digest) in targets.items():
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise SystemExit('Concurrent update: ' + str(path))
    if name.endswith('.py'): py_compile.compile(str(stage/name), doraise=True)
pid = int(subprocess.check_output(['systemctl','show','swr-push-helper','-p','MainPID','--value']))
started = time.time() - float(Path('/proc/uptime').read_text().split()[0]) + int(Path(f'/proc/{pid}/stat').read_text().split()[21])/os.sysconf('SC_CLK_TCK')
for file in (root/'logs').glob('job-*.json'):
    job = json.loads(file.read_text())
    if job.get('status') in ('running','queued') and file.stat().st_mtime >= started:
        raise SystemExit('Active Robot job: ' + job['id'])
backup = Path('/var/backups/pr-e2e') / ('gamma-general-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True)
for name, (path, _) in targets.items():
    shutil.copy2(path, backup/name)
    shutil.copyfile(stage/name, path)
subprocess.run(['systemctl','restart','swr-push-helper'], check=True)
print('DEPLOYED', backup)
