"""The existing single Worker owns Gamma claims; a narrow root helper runs CCE access."""
import json
import os
from pathlib import Path
import re
import subprocess
import time

from control_client import rpc
from pr_pipeline_hub import atomic_json, utc_now


def execute(hub, claim):
    run = dict(claim['run'])
    run_id = run['id']
    if not re.fullmatch(r'gamma-[0-9a-f]{24}', run_id):
        raise ValueError('Invalid Gamma queue ID')
    root = Path('/var/lib/pr-e2e/gamma-claims')
    root.mkdir(mode=0o700, exist_ok=True)
    private = root / (run_id + '.json')
    atomic_json(private, {'id': run_id, 'lease_token': claim['lease_token'],
                         'generation': run['execution_generation']})
    private.chmod(0o600)
    state = Path('/var/lib/pr-gamma-executor') / run_id / 'progress.json'
    log_dir = hub.runs_dir / run_id
    log_dir.mkdir(parents=True, exist_ok=True)
    lost = False
    last_ack = time.monotonic()
    run.update(status='running', started_at=utc_now(), summary='准备冻结 Gamma 验收环境')
    def update(final=False):
        if not final and state.exists():
            run.update(json.loads(state.read_text()))
        return rpc(f"/internal/runs/{run_id}/{'finish' if final else 'progress'}",
                   {'lease_token': claim['lease_token'], 'patch': run})
    update()
    with (log_dir / 'gamma-worker.log').open('a') as log:
        process = subprocess.Popen(['sudo', '-n', '/usr/local/sbin/pr-gamma-execute', run_id],
                                   stdout=log, stderr=subprocess.STDOUT)
        while process.poll() is None:
            if lost:
                time.sleep(5)
                continue
            try:
                update()
                last_ack = time.monotonic()
            except Exception as error:
                log.write(utc_now() + ' heartbeat failure: ' + type(error).__name__ + '\n')
                log.flush()
                if '409' in str(error) or time.monotonic() - last_ack > 90:
                    # Root helper checks the same lease; it must exit without new mutations.
                    lost = True
            time.sleep(30)
        code = process.returncode
    if lost:
        run.update(status='interrupted', conclusion='error', summary='环境租约丢失，等待恢复检查')
        atomic_json(log_dir / 'run.json', run)
        return
    if state.exists():
        run.update(json.loads(state.read_text()))
    if run.get('status') not in ('completed', 'interrupted') or (code != 0 and run.get('status') != 'interrupted'):
        run.update(status='interrupted', conclusion='error', summary='Gamma 执行器未完成安全收尾',
                   cleanup={'status': 'unknown'}, environment_health='quarantined')
    update(final=True)
