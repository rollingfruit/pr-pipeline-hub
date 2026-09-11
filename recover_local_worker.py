"""Explicit local recovery with environment-lock and process reconciliation."""
import argparse
import fcntl
import json
import os
from pathlib import Path
from control_client import rpc
from e2e_runner import load_stack

parser = argparse.ArgumentParser()
parser.add_argument('run_id')
args = parser.parse_args()
state = load_stack().STATE
root = (state/'pipeline/runs').resolve()
folder = (root/args.run_id).resolve()
if folder.parent != root:
    raise ValueError('Invalid run ID')
run = json.loads((folder/'run.json').read_text())
if run['status'] != 'interrupted':
    raise ValueError('Local run is not interrupted')
with (state/'environment.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    for process in Path('/proc').glob('[0-9]*'):
        if int(process.name) == os.getpid():
            continue
        try:
            comm = (process/'comm').read_text().strip()
            if comm in {'codex','node','git','bash','docker'} and args.run_id.encode() in (process/'cmdline').read_bytes():
                raise RuntimeError('Run-owned process still active: '+process.name)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    print(json.dumps(rpc('/internal/recover/'+args.run_id, {
        'environment_unlocked':True, 'processes_reconciled':True,
        'reason':'Local process reconciliation after SSH heartbeat interruption',
        'result':{k:run.get(k) for k in ('review','stages','error','failure_stage','test_results','suites','policy','merge_conflicts')}})))
