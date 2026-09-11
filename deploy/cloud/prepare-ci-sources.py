"""Fetch committed baseline sources with the CI profile, without running repo code."""
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, '/opt/pr-pipeline-ci')
from cloud_config import load, activate

cfg = load('/etc/pr-e2e/config.toml', 'worker', True)
activate(cfg, 'worker')
sys.path.insert(0, cfg['paths']['stack'])
from stack import SOURCE_REPOS, output_json

root = Path(cfg['paths']['workspace'])
records = []
env = {**os.environ, 'GIT_LFS_SKIP_SMUDGE': '1', 'GIT_TERMINAL_PROMPT': '0'}
git = ['git', '-c', 'credential.helper=', '-c', 'credential.helper=!/usr/local/bin/gh auth git-credential']
for name in SOURCE_REPOS:
    target = root / name
    if not target.exists():
        subprocess.run(git + ['clone', '--filter=blob:none', '--single-branch',
                             'https://github.com/rollingfruit/' + name + '.git', str(target)],
                       env=env, check=True, timeout=900)
    sha = subprocess.check_output(['git', '-C', str(target), 'rev-parse', 'HEAD'], text=True).strip()
    records.append({'repository': name, 'sha': sha})
    print(json.dumps(records[-1]), flush=True)
output_json(Path(cfg['paths']['state']) / 'prepared-sources.json', records)
