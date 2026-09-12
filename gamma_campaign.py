"""Privileged Gamma executor. Claims originate only from the existing single Worker."""
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import time


def main():
    if os.geteuid() != 0 or len(sys.argv) != 2 or not re.fullmatch(r'gamma-[0-9a-f]{24}', sys.argv[1]):
        raise SystemExit('Root queue executor with one Gamma ID required')
    run_id = sys.argv[1]
    claim = Path('/var/lib/pr-e2e/gamma-claims') / (run_id + '.json')
    account = pwd.getpwnam('pr-e2e')
    if claim.is_symlink() or claim.stat().st_uid != account.pw_uid or claim.stat().st_mode & 0o077:
        raise SystemExit('Invalid private claim ownership')
    os.environ.update(PIPELINE_CONTROL_URL='http://127.0.0.1:8792',
                      PIPELINE_WORKER_TOKEN=Path('/etc/pr-e2e/secrets/worker-token').read_text().strip(),
                      GAMMA_LEASE_FILE=str(claim))
    from gamma_lease import check
    from control_client import rpc
    check()
    run = rpc('/api/runs/' + run_id)
    if run.get('kind') != 'gamma' or run.get('status') != 'running':
        raise SystemExit('Canonical queue record is not executable')
    request = run['gamma_request']
    from gamma_queue import validate
    validate(request)
    if request.get('build_manifest'):
        path = Path(request['build_manifest'])
        if path.is_symlink() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
            raise ValueError('Untrusted build manifest')
        from gamma_freeze import digest
        if digest(path) != request['build_manifest_sha256']:
            raise ValueError('Queued build manifest was modified')
    root = Path('/var/lib/pr-gamma-executor') / run_id
    root.mkdir(parents=True, mode=0o750)
    os.chown(root, 0, account.pw_gid)
    state = {'status': 'running', 'rounds': [], 'target_rounds': request['rounds'],
             'cleanup': {'status': 'pending'}, 'environment_health': 'checking'}
    def save():
        from gamma_statistics import statistics
        state['statistics'] = statistics(state['rounds'], state.get('started_rounds', 0), request['rounds'],
                                         active=state['status'] == 'running')
        temporary = root / 'progress.tmp'
        temporary.write_text(json.dumps(state, ensure_ascii=False))
        os.chown(temporary, 0, account.pw_gid)
        temporary.chmod(0o640)
        temporary.replace(root / 'progress.json')
    save()
    from gamma_access import GammaAccess
    from gamma_freeze import create, verify
    access = GammaAccess(request['environment_id'])
    try:
        access.connect()
        if request['mode'] == 'deploy':
            from gamma_rollout import GammaRollout
            path = Path(request['build_manifest'])
            if path.is_symlink() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
                raise ValueError('Untrusted build manifest')
            manifest = json.loads(path.read_text())
            if manifest['environment_id'] != request['environment_id'] or not manifest.get('deploy'):
                raise ValueError('Deployment manifest mismatch')
            rollout = GammaRollout(access, manifest, root)
            try:
                state['rollout'] = rollout.prepare()
                rollout.apply()
                from gamma_readiness import wait_for_deployments
                state['runtime_image_manifest'] = wait_for_deployments(access, {rollout.deploy})
                state.update(status='completed', conclusion='success', summary='部署完成；未执行 E2E',
                             cleanup={'status': 'passed', 'active_residuals': [], 'created': {}},
                             environment_health='ready')
            except Exception:
                if rollout.applied:
                    state['rollback'] = rollout.rollback()
                raise
            return 0
        if request.get('build_manifest') and request['mode'] == 'stability':
            raise ValueError('Freeze current verified environment; stability jobs cannot deploy between rounds')
        frozen = create(root, access)
        state['frozen_environment'] = frozen['environment']
        state['harness_fingerprint'] = __import__('hashlib').sha256(json.dumps(frozen['files'], sort_keys=True).encode()).hexdigest()
        state['model'] = frozen['model']
        state['daemon_sha256'] = frozen['daemon_sha256']
        state['summary'] = '冻结完成，开始执行'
        save()
        for index in range(request['rounds']):
            check()
            verify(root, access)
            state.update(current_round=index + 1, started_rounds=index + 1, summary=f"正在执行第 {index + 1}/{request['rounds']} 轮")
            save()
            args = ['/usr/local/bin/python3.11', str(root / 'frozen/gamma_acceptance.py'),
                    '--environment-id', request['environment_id'], '--suites', *request['suite_ids']]
            if request.get('build_manifest'):
                args += ['--build-manifest', request['build_manifest']]
            child_id = None
            env = {**os.environ, 'GAMMA_FROZEN_ROOT': str(root / 'frozen'),
                   'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': '/opt/pr-pipeline-ci'}
            with (root / f'round-{index + 1}.log').open('w') as log:
                with subprocess.Popen(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as process:
                    for line in process.stdout:
                        log.write(line)
                        log.flush()
                        if line.startswith('PIPELINE_URL='):
                            child_id = line.strip().rsplit('/', 1)[-1]
                            state['active_run_id'] = child_id
                            save()
                    code = process.wait()
            if not child_id or not re.fullmatch(r'gamma-check-[0-9-]+[a-f0-9]+', child_id):
                raise RuntimeError('Child execution did not publish a valid report')
            archive = Path('/var/lib/pr-e2e-share/runs') / child_id
            child = json.loads((archive / 'run.json').read_text())
            if child.get('daemon_sha256') and child['daemon_sha256'] != frozen['daemon_sha256'] and not request.get('build_manifest'):
                raise RuntimeError('Child Daemon differs from frozen experiment')
            from gamma_freeze import digest
            hashes = child.get('archive_manifest', [])
            archived = bool(hashes) and all((archive / p['path']).resolve().is_relative_to(archive.resolve())
                        and digest(archive / p['path']) == p['sha256'] for p in hashes)
            success = code == 0 and child.get('conclusion') == 'success' and archived and not child.get('stale')
            row = {'index': index + 1, 'run_id': child_id, 'first_pass': success,
                   'failure_kind': 'assertion_failure' if child.get('conclusion') == 'failure' else 'environment_error' if child.get('conclusion') == 'error' else 'unknown',
                   'conclusion': child.get('conclusion'), 'summary': child.get('summary'),
                   'started_at': child.get('started_at'), 'finished_at': child.get('finished_at'),
                   'tests': child.get('test_results', []), 'cleanup': child.get('cleanup'), 'archive_verified': archived}
            state['rounds'].append(row)
            state['cleanup'] = child.get('cleanup', {'status': 'unknown'})
            state['completed_rounds'] = len(state['rounds'])
            state['first_pass_count'] = sum(r['first_pass'] for r in state['rounds'])
            state['first_pass_rate'] = state['first_pass_count'] / state['completed_rounds']
            save()
            if not archived or state['cleanup'].get('status') != 'passed' or child.get('stale') or child.get('conclusion') == 'error':
                raise RuntimeError('Environment/model/archive/cleanup failure; experiment paused')
            if not request.get('build_manifest'):
                verify(root, access)
        state.update(status='completed', conclusion='success' if state['first_pass_count'] == request['rounds'] else 'failure',
                     environment_health='ready', publication={'status': 'published'},
                     summary=f"首次通过 {state['first_pass_count']}/{request['rounds']}；已保留每轮原始结果")
    except Exception as error:
        state.update(status='interrupted', conclusion='error', environment_health='quarantined',
                     summary='暂停，需恢复检查: ' + type(error).__name__ + ': ' + str(error)[:200])
    finally:
        access.close()
        save()
    return 0 if state['status'] == 'completed' else 1


if __name__ == '__main__':
    sys.exit(main())
