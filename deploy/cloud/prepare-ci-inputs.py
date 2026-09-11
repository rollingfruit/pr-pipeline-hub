"""Copy existing CI build inputs into owned storage, recording content hashes."""
import os
from pathlib import Path
import pwd
import shutil
import sys

sys.path.insert(0, '/opt/pr-pipeline-ci/stack')
from sync_inputs import FILES, digest
from stack import output_json

account = pwd.getpwnam('pr-e2e')
destination = Path('/var/lib/pr-e2e/state/build-inputs')
destination.mkdir(exist_ok=True)
os.chown(destination, account.pw_uid, account.pw_gid)
records = []
for name in FILES:
    source = Path('/opt/ai/installers') / name
    if not source.is_file():
        records.append({'name': name, 'status': 'missing'})
        continue
    before = digest(source)
    target = destination / name
    if not target.is_file() or digest(target) != before:
        temporary = target.with_suffix(target.suffix + '.partial')
        shutil.copyfile(source, temporary)
        if digest(temporary) != before:
            raise ValueError('Input changed during copy: ' + name)
        os.chown(temporary, account.pw_uid, account.pw_gid)
        temporary.replace(target)
    records.append({'name': name, 'sha256': before, 'size': target.stat().st_size, 'status': 'verified'})
    print(name + ': verified', flush=True)
output_json(destination / 'build-inputs.lock.json', {'source': '/opt/ai/installers', 'files': records})
runner=destination.parent/'cce-test-runner'
runner.mkdir(exist_ok=True)
os.chown(runner,account.pw_uid,account.pw_gid)
runner_hashes={}
for name in ('unittest_case_runner.py','shell_case_runner.py'):
    source=Path('/opt/swr-push-helper')/name
    shutil.copyfile(source,runner/name)
    os.chown(runner/name,account.pw_uid,account.pw_gid)
    runner_hashes[name]=digest(runner/name)
output_json(runner/'manifest.json',runner_hashes)
