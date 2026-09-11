"""Root operator acceptance via Robot CI's deployed post-build entry point.

Reuses a successful image build, creates a separate history record, and never
changes the original failed job. This is not a browser submission.
"""
import json
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, '/opt/swr-push-helper')
import server

old = json.loads((server.LOG_DIR / 'job-82cf0e6101c8.json').read_text())
job_id = uuid.uuid4().hex[:12]
job = {**old, 'id': job_id, 'operator': 'CI-operator-acceptance', 'client_id': '',
       'created_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'finished_at': '',
       'status': 'running', 'stage': 'gamma', 'error': None, 'gamma_e2e': None,
       'log': [], 'ui_log': [], 'step_logs': {}, 'slot_held': False, 'cancel_requested': False,
       'log_file': str(server.LOG_DIR / ('job-' + job_id + '.log'))}
conflict = server.register_concurrent_job(job)
if conflict:
    raise SystemExit('Robot CI admission conflict')
server._job_ctx.job_id = job_id
server.persist_job_meta(job_id)
server.append_job_log(job_id, 'Operator acceptance: reuse immutable SWR artifact from build 82cf0e6101c8; no rebuild')
print('ROBOT_JOB=' + job_id, flush=True)
try:
    ok, error = server.maybe_run_gamma_after_build(job_id, old['results'])
    server.set_job(job_id, status='ok' if ok else 'failed', stage='done', error=error or None)
    print('ROBOT_RESULT', ok, error, flush=True)
    print(json.dumps(server._job_copy(job_id).get('gamma_e2e')), flush=True)
except Exception as exc:
    server.set_job(job_id, status='failed', error=str(exc))
    raise
finally:
    server.release_build_slot(job_id)
sys.exit(0 if ok else 1)
