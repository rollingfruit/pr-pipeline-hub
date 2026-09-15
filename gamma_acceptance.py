"""Real dev-gamma E2E, optionally deploying a verified Robot CI build artifact."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
import threading
import urllib.request

from gamma_access import GammaAccess


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temporary.chmod(0o600)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--environment-id', default='a5932430eb2f')
    parser.add_argument('--build-manifest')
    parser.add_argument('--suites', nargs='+', choices=['E01', 'E02', 'E03', 'E04', 'E05', 'E06'], default=['E01', 'E02', 'E03'])
    args = parser.parse_args()
    from gamma_lease import check as check_lease
    check_lease()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', args.environment_id):
        parser.error('Invalid Robot CI environment ID')
    args.suites = list(dict.fromkeys(args.suites))
    build = None
    if args.build_manifest:
        manifest = Path(args.build_manifest).resolve(strict=True)
        if not manifest.is_relative_to(Path('/var/lib/pr-e2e/build-inbox')) or manifest.stat().st_uid != 0 or manifest.stat().st_mode & 0o022:
            parser.error('Trusted private build manifest required')
        build = json.loads(manifest.read_text())
        if build['environment_id'] != args.environment_id:
            parser.error('Environment mismatch')
        if build.get('suite_ids') is not None and build['suite_ids'] != args.suites:
            parser.error('Selected suites differ from the frozen build handoff')
    account = pwd.getpwnam('pr-e2e')
    viewer = pwd.getpwnam('prpipeline')
    run_id = 'gamma-check-' + time.strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3)
    root = Path('/var/lib/pr-gamma-executor/diagnostics') / run_id
    private = root / 'private'
    private.mkdir(parents=True, mode=0o700)
    archive = Path('/var/lib/pr-e2e-share/runs') / run_id
    archive.mkdir(parents=True, mode=0o750)
    os.chown(archive, viewer.pw_uid, viewer.pw_gid)
    stages = [{'id': key, 'name': label, 'status': 'queued', 'conclusion': None}
              for key, label in [('preflight', 'dev-gamma 访问与冻结镜像'), ('bootstrap', '专用测试账号与 Runtime')]
              + [(s, {'E01':'创建机器人','E02':'私聊执行与追问','E03':'群聊 @ 与回复',
                      'E04':'停止与取消','E05':'失败可见性','E06':'重复事件与幂等'}[s]) for s in args.suites]
              + [('report', '归档真实证据')]]
    redactions = []
    if build:
        stages.insert(1, {'id': 'deploy', 'name': '部署本次 SWR 镜像', 'status': 'queued', 'conclusion': None})
        stages.insert(-1, {'id': 'restore', 'name': '失败恢复检查', 'status': 'queued', 'conclusion': None})
    run = {'id': run_id, 'title': 'dev-gamma 当前环境真实 E2E 诊断', 'created_at': now(),
           'started_at': now(), 'status': 'running', 'repo': 'rollingfruit/agent-governance-gw',
           'source_mode': 'environment', 'diagnostic': True, 'full_acceptance': False,
           'execution_location': 'ecs-liusong-ci', 'environment_id': args.environment_id,
           'requested_by': 'operator', 'trigger_source': 'manual_environment_diagnostic',
           'profile': 'browser-e2e', 'stages': stages, 'test_results': [],
           'suites': [{'id': s, 'name': s, 'kind': {'E05':'resilience','E06':'hybrid'}.get(s,'browser'),
                       'reason':'用户选择', 'implemented': True} for s in args.suites],
           'summary': '验证已有 dev-gamma 镜像；不构建、不部署、不作合入结论',
           'github': {'state': 'disabled'}, 'environment_status': 'running',
           'review': {'status': 'disabled', 'summary': '本次只执行环境 E2E', 'findings': []}}
    if build:
        run.update(title='dev-gamma 构建产物部署与真实 E2E', diagnostic=False,
                   trigger_source=build.get('trigger_source', 'robot_ci_build'),
                   repo=build['result']['service_id'],
                   build_result={'build_id': build['build_id'], 'source_sha': build['result']['commit_sha'],
                                 'image': build['pinned_image'], 'image_id': build['image_id']},
                   summary='验证本次构建产物，不作 PR 合入结论')
    state_lock = threading.RLock()
    def save():
        with state_lock:
            _save()
    def _save():
        serialized = json.dumps(run, ensure_ascii=False)
        for secret in redactions:
            if secret:
                serialized = serialized.replace(secret, '[REDACTED]')
        write(archive / 'run.json', json.loads(serialized))
        os.chown(archive / 'run.json', viewer.pw_uid, viewer.pw_gid)
        os.chmod(archive / 'run.json', 0o640)
    active = stages[0]
    def start(id):
        nonlocal active
        if id not in ('report', 'restore'):
            check_lease()
        active = next(s for s in stages if s['id'] == id)
        active.update(status='running', started_at=now())
        save()
        print('Gamma stage: ' + active['name'], flush=True)
    def finish(ok=True):
        active.update(status='completed', conclusion='success' if ok else 'failure', finished_at=now())
        save()
    def stage_start(id):
        check_lease()
        with state_lock:
            stage = next(s for s in stages if s['id'] == id)
            stage.update(status='running', started_at=now())
            save()
        print('Gamma stage: ' + stage['name'], flush=True)
        return stage
    def stage_finish(stage, ok=True):
        with state_lock:
            stage.update(status='completed', conclusion='success' if ok else 'failure', finished_at=now())
            save()
    save()
    print('PIPELINE_URL=http://119.8.233.58/pipeline/runs/' + run_id, flush=True)
    access = GammaAccess(args.environment_id)
    env = None
    rollout = None
    def sanitize(text):
        for secret in redactions:
            if secret:
                text = text.replace(secret, '[REDACTED]')
        return text
    def command(argv, cwd=None, timeout=600, log_name=None, command_env=None):
        with (root / ((log_name or active['id']) + '.log')).open('w') as log:
            result = subprocess.run(['/usr/sbin/runuser', '-u', 'pr-e2e', '--', *map(str, argv)],
                cwd=cwd, env=command_env or env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        return result.returncode
    # All per-module environment IDs share one cluster and therefore one lock.
    lock = (root.parent / 'dev-gamma.lock').open('a')
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            run['summary'] = '等待 dev-gamma 环境锁'
            save()
            while True:
                check_lease()
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(5)
        start('preflight')
        access.connect()
        resources = access.resource('services')['items']
        def address(app):
            found = [s for s in resources if s['spec'].get('selector', {}).get('app') == app]
            if len(found) != 1:
                raise RuntimeError('Expected one service for ' + app)
            return found[0]['spec']['clusterIP']
        app_url = access.forward(address('service-router'), 80, 0)
        multica_url = access.forward(address('multica-server'), 8080, 0)
        with urllib.request.urlopen(app_url + '/api/v4/system/ping', timeout=20) as response:
            if json.load(response).get('status') != 'OK':
                raise RuntimeError('Mattermost is not healthy')
        frozen = []
        for obj in access.resource('deployments')['items']:
            name = obj['metadata']['name']
            frozen.append({'name': name, 'uid': obj['metadata']['uid'],
                'template': obj['spec']['template'], 'generation': obj['metadata']['generation']})
        # Keep complete templates private: environment variables may contain secrets.
        write(private / 'deployment-snapshot.json', frozen)
        run['image_manifest'] = [{'name': item['name'], 'generation': item['generation'],
            'images': [c['image'] for c in item['template']['spec']['containers']]} for item in frozen]
        finish()
        if build:
            start('deploy')
            from gamma_rollout import GammaRollout
            rollout = GammaRollout(access, build, private)
            run['rollout'] = rollout.prepare()
            snapshot = next((s for s in frozen if s['name'] == rollout.deploy), None)
            if not snapshot or snapshot['template'] != rollout.before['spec']['template']:
                raise RuntimeError('Deployment changed before rollout')
            save()
            if build['deploy']:
                rollout.apply()
            elif run['rollout']['before'] != build['pinned_image']:
                raise RuntimeError('Test-only mode requires the exact built image to be already deployed')
            for item in frozen:
                obj = access.resource('deployment', item['name'])
                expected = rollout.expected if item['name'] == rollout.deploy and build['deploy'] else item['template']
                if obj['metadata']['uid'] != item['uid'] or obj['spec']['template'] != expected:
                    run['stale'] = True
                    raise RuntimeError('Environment changed during rollout: ' + item['name'])
                item.update(template=obj['spec']['template'], generation=obj['metadata']['generation'])
            run['image_manifest'] = [{'name': item['name'], 'generation': item['generation'],
                'images': [c['image'] for c in item['template']['spec']['containers']]} for item in frozen]
            finish()
        start('bootstrap')
        from gamma_readiness import wait_for_deployments
        required = {'service-router', 'mattermost', 'agent-link', 'semantic-gateway', 'semantic-schedule', 'governance', 'multica-server'}
        if build:
            required.add(rollout.deploy)
        run['runtime_image_manifest'] = wait_for_deployments(access, required)
        save()
        namespace = shlex.quote(access.namespace)
        token = access.remote(f'kubectl -n {namespace} exec deployment/multica-server -- printenv SERVICE_INTERNAL_TOKEN').strip()
        if not token:
            raise RuntimeError('Multica internal authentication not configured')
        redactions.append(token)
        write(private / 'internal.json', {'token': token})
        cli = root / 'bin/multica'
        cli.parent.mkdir()
        request = urllib.request.Request(multica_url + '/v1/agent/im-integrations/connector-binaries?os=linux&arch=amd64',
                                         headers={'X-Auth-Token': token})
        with urllib.request.urlopen(request, timeout=120) as response, cli.open('wb') as out:
            shutil.copyfileobj(response, out)
        cli.chmod(0o755)
        digest = hashlib.sha256(cli.read_bytes()).hexdigest()
        expected = access.remote(f'kubectl -n {namespace} exec deployment/multica-server -- sha256sum /opt/ai/multica-server/connector-assets/multica-linux-amd64').split()[0]
        if digest != expected:
            raise RuntimeError('Daemon binary does not match deployed Multica image')
        run['daemon_sha256'] = digest
        source = Path(os.environ.get('GAMMA_FROZEN_ROOT', '/opt/pr-pipeline-ci')) / 'stack'
        stack = root / 'stack'
        stack.mkdir()
        for name in ('stack.py', 'bootstrap.py', 'local_daemon.py', 'fault-control.py'):
            shutil.copy2(source / name, stack / name)
        shutil.copytree(source / 'playwright', stack / 'playwright',
                        ignore=shutil.ignore_patterns('node_modules', 'results', 'test-results'))
        dependencies = Path(os.environ.get('GAMMA_FROZEN_ROOT', '/var/lib/pr-e2e/state/playwright')) / 'node_modules'
        (stack / 'playwright/node_modules').symlink_to(dependencies)
        base = json.loads(Path('/var/lib/pr-e2e/state/settings.json').read_text())
        password = secrets.token_urlsafe(24) + '!7aA'
        redactions.append(password)
        cfg = {k: base[k] for k in ('OPENCODE_CONFIG', 'OPENCODE_MODEL')}
        workspace = root / 'workspace'
        workspace.mkdir()
        cfg.update(AGENT_PROVIDER='opencode', TEST_ADMIN_USER='gamma-e2e-' + secrets.token_hex(5),
            OPENCODE_FIXTURE_ACCESS=True, E2E_SINGLE_PROVIDER=True,
            E2E_RESILIENCE_ENABLED='E05' in args.suites,
            E2E_FAILURE_TIMEOUT_SECONDS=int(os.environ.get('GAMMA_E2E_FAILURE_TIMEOUT_SECONDS', '165')),
            TEST_ADMIN_PASSWORD=password, TEST_WORKSPACE=str(workspace), CODEX_PROXY='',
            LOCAL_DAEMON_PROFILE='pr-e2e-gamma-' + secrets.token_hex(4))
        cfg['TEST_ADMIN_EMAIL'] = cfg['TEST_ADMIN_USER'] + '@example.invalid'
        run['provider_scope'] = 'opencode-only; multi-provider selection is not covered'
        # Do not set a profile until its first daemon start; connect() probes existing profiles.
        cfg.pop('LOCAL_DAEMON_PROFILE')
        write(private / 'settings.json', cfg)
        for folder, dirs, files in os.walk(root, followlinks=False):
            os.chown(folder, account.pw_uid, account.pw_gid)
            for name in dirs + files:
                path = Path(folder) / name
                if not path.is_symlink():
                    os.chown(path, account.pw_uid, account.pw_gid)
        # The tested Agent must not edit the harness or downloaded Daemon.
        for folder, dirs, files in os.walk(stack, followlinks=False):
            os.chown(folder, 0, 0)
            os.chmod(folder, 0o555)
            for name in files:
                path = Path(folder) / name
                if not path.is_symlink():
                    os.chown(path, 0, 0)
                    path.chmod(0o444)
        os.chown(cli, 0, 0)
        env = {'PATH': str(cli.parent) + ':/opt/pr-pipeline-tools/bin:/opt/pr-pipeline-ci/.venv/bin:/var/lib/pr-e2e/state/tools/node24.18.0/bin:/usr/local/bin:/usr/bin:/bin',
            'HOME': str(root), 'E2E_STATE_DIR': str(root / 'state'),
            'E2E_SETTINGS_FILE': str(private / 'settings.json'), 'E2E_SETTINGS': str(private / 'settings.json'),
            'E2E_PRIVATE_DIR': str(private), 'E2E_APP_URL': app_url, 'E2E_MULTICA_URL': multica_url,
            'E2E_PYTHON': sys.executable,
            'E2E_DISCOVER_BROWSER_IDENTITY': '1',
            'PIPELINE_CLOUD_PROFILE': '1',
            'PLAYWRIGHT_BROWSERS_PATH': '/var/lib/pr-e2e/.cache/ms-playwright',
            'NODE_EXTRA_CA_CERTS': '/etc/pki/tls/certs/ca-bundle.crt', 'SSL_CERT_FILE': '/etc/pki/tls/certs/ca-bundle.crt',
            'NO_PROXY': '127.0.0.1,localhost,::1'}
        if command(['/opt/pr-pipeline-ci/.venv/bin/python', stack / 'bootstrap.py'], timeout=240):
            raise RuntimeError('Dedicated test identity/runtime preparation failed; see bootstrap log')
        prepared = json.loads((private / 'settings.json').read_text())
        configured_workspace = access.remote('kubectl -n ' + namespace +
            ' exec deployment/multica-server -- printenv MULTICA_WORKSPACE_ID').strip()
        if prepared.get('WORKSPACE_ID') != configured_workspace:
            raise RuntimeError('Test Workspace differs from Multica administrative scope; configuration repair required')
        identity = json.loads((private / 'bootstrap.json').read_text())
        owner = {'run_id': run_id, 'user_id': identity['user_id'], 'username': prepared['TEST_ADMIN_USER'],
                 'email': prepared['TEST_ADMIN_EMAIL'], 'daemon_id': prepared['DAEMON_ID'],
                 'workspace_id': prepared['WORKSPACE_ID']}
        write(root / 'ownership.json', owner)
        from gamma_admin import MattermostAdmin
        MattermostAdmin(access).fixture(owner)
        # Writable fixture directories remain available, but cannot replace the harness.
        os.chown(root, 0, account.pw_gid)
        root.chmod(0o750)
        frozen_settings = root / 'frozen-settings.json'
        shutil.copyfile(private / 'settings.json', frozen_settings)
        os.chown(frozen_settings, 0, account.pw_gid)
        frozen_settings.chmod(0o640)
        env.update(E2E_SETTINGS_FILE=str(frozen_settings), E2E_SETTINGS=str(frozen_settings),
                   E2E_FROZEN_SETTINGS=str(frozen_settings))
        auth_state = private / 'playwright-auth.json'
        auth_env = {**env, 'E2E_AUTH_STATE': str(auth_state)}
        if command(['node', stack / 'playwright/auth-state.cjs'], stack / 'playwright',
                   timeout=120, log_name='playwright-auth', command_env=auth_env):
            raise RuntimeError('Browser login state preparation failed; see playwright-auth log')
        auth_state.chmod(0o600)
        env['E2E_AUTH_STATE'] = str(auth_state)
        (root / 'evidence').mkdir(exist_ok=True)
        os.chown(root / 'evidence', account.pw_uid, account.pw_gid)
        finish()
        from e2e_catalog import validate_result
        from e2e_execution_graph import waves
        failed = []
        failed_lock = threading.Lock()
        run['execution_plan'] = {'max_parallel': 2, 'waves': waves(args.suites, 2),
                                 'exclusive': ['E05'], 'login_state': 'shared-per-run'}
        save()
        def run_suite(suite):
            stage = stage_start(suite)
            output = root / 'evidence' / suite
            suite_env = {**env, 'E2E_SUITE': suite, 'E2E_OUTPUT': str(output), 'E2E_RUN_ID': run_id,
                         'E2E_FAULT_CONTROL': str(stack / 'fault-control.py')}
            code = command(['node', dependencies / '@playwright/test/cli.js',
                            'test', '-c', 'playwright.config.ts'], stack / 'playwright', timeout=900,
                           log_name=suite, command_env=suite_env)
            evidence = output / 'evidence.json'
            payload = json.loads(evidence.read_text()) if evidence.exists() else {}
            with state_lock:
                run['test_results'].extend(payload.get('tests', []))
            try:
                validate_result(payload, suite)
                if code: raise ValueError('Browser process failed')
                stage_finish(stage)
            except ValueError:
                with failed_lock:
                    failed.append(suite)
                stage_finish(stage, False)
        for wave in run['execution_plan']['waves']:
            check_lease()
            with ThreadPoolExecutor(max_workers=min(2, len(wave))) as executor:
                futures = [executor.submit(run_suite, suite) for suite in wave]
                for future in as_completed(futures):
                    future.result()
        for item in frozen:
            latest = access.resource('deployment', item['name'])
            if latest['metadata']['uid'] != item['uid'] or latest['spec']['template'] != item['template']:
                run['stale'] = True
        run['conclusion'] = 'failure' if failed else 'error' if run.get('stale') else 'success'
        run['summary'] = ('未通过: ' + ', '.join(failed)) if failed else ('本次构建镜像验证通过：' + ', '.join(args.suites) if build else '所选用例通过（仅当前环境诊断）')
        if run.get('stale'): run['summary'] += '；运行期间镜像或配置被外部更新'
    except Exception as error:
        finish(False)
        run.update(conclusion='error', failure_stage=active['id'], summary=sanitize(str(error)))
        print('BLOCKED:', sanitize(str(error)), flush=True)
    finally:
        if rollout and rollout.applied and run.get('conclusion') != 'success':
            start('restore')
            try:
                run['rollback'] = rollout.rollback()
                finish()
            except Exception as error:
                run['rollback'] = 'manual_intervention_required'
                run['summary'] += '; rollback: ' + sanitize(str(error))
                run['conclusion'] = 'error'
                finish(False)
        # Evidence is copied before destructive business cleanup.
        for path in (root / 'evidence').rglob('*') if (root / 'evidence').exists() else []:
            if path.is_file() and path.suffix in {'.png', '.webm', '.json', '.ndjson'}:
                target = archive / 'artifacts/current' / path.relative_to(root / 'evidence')
                target.parent.mkdir(parents=True, exist_ok=True)
                if path.suffix in {'.json', '.ndjson'}:
                    target.write_text(sanitize(path.read_text(errors='replace')))
                else:
                    shutil.copy2(path, target)
        if env:
            try:
                check_lease()
                from gamma_cleanup import cleanup
                run['cleanup'] = cleanup(root, env, access)
            except Exception as error:
                run['cleanup'] = {'status': 'failed', 'error_type': type(error).__name__}
        else:
            run['cleanup'] = {'status': 'not_started', 'active_residuals': []}
        if run['cleanup']['status'] != 'passed':
            run['conclusion'] = 'error'
            run['summary'] += '；环境清理未通过，暂停后续执行'
        access.close()
        for stage in stages:
            if stage['status'] == 'queued': stage.update(status='completed', conclusion='skipped')
        start('report')
        for path in root.glob('*.log'):
            (archive / path.name).write_text(sanitize(path.read_text(errors='replace')))
        for path in (root / 'evidence').rglob('*') if (root / 'evidence').exists() else []:
            if not path.is_file() or path.suffix not in {'.png', '.webm', '.json', '.ndjson'}:
                continue
            target = archive / 'artifacts/current' / path.relative_to(root / 'evidence')
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix in {'.json', '.ndjson'}:
                target.write_text(sanitize(path.read_text(errors='replace')))
            else:
                shutil.copy2(path, target)
        run['evidence_notice'] = 'Trace ZIP 和完整模板仅保留在 CI 私有目录，避免泄露登录凭据'
        run['archive_manifest'] = [{'path': str(p.relative_to(archive)),
            'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size}
            for p in archive.rglob('*') if p.is_file() and p.name != 'run.json']
        run.update(status='completed', finished_at=now(), environment_status=(
            'test_runtime_stopped' if run['cleanup']['status'] == 'passed' else 'quarantined'))
        finish()
        for folder, dirs, files in os.walk(archive):
            os.chown(folder, viewer.pw_uid, viewer.pw_gid)
            os.chmod(folder, 0o750)
            for name in files:
                os.chown(Path(folder) / name, viewer.pw_uid, viewer.pw_gid)
                os.chmod(Path(folder) / name, 0o640)
        print('RESULT', run['conclusion'], run['summary'], flush=True)
        lock.close()
    return 0 if run['conclusion'] == 'success' else 1


if __name__ == '__main__':
    sys.exit(main())
