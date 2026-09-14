"""Root-only, evidence-gated repair of a quarantined task, under its queue lock."""
import argparse
import json
import os
from pathlib import Path
import pwd
import shlex
import sys
import time
sys.path.insert(0, '/opt/pr-pipeline-ci')
sys.path.insert(0, '/opt/pr-e2e-share')
from control_store import Store
from psycopg.types.json import Jsonb
from gamma_access import GammaAccess
from gamma_cleanup import cleanup, residual_processes
from gamma_freeze import digest
from gamma_readiness import wait_for_deployments

parser = argparse.ArgumentParser()
parser.add_argument('run_id')
parser.add_argument('--align-workspace', action='store_true')
args = parser.parse_args()
if os.geteuid() != 0:
    raise SystemExit('Root operator required')
dsn = next(line.split('=', 1)[1].strip().strip('"').strip("'") for line in Path('/etc/pr-pipeline-control.env').read_text().splitlines() if line.startswith('PIPELINE_DATABASE_URL='))
store = Store(dsn)
access = GammaAccess('a5932430eb2f')
evidence = {}
try:
    with store.db() as db:
        db.execute('SELECT pg_advisory_xact_lock(91807912)')
        row = db.execute('SELECT * FROM reviews WHERE id=%s FOR UPDATE', (args.run_id,)).fetchone()
        lease = db.execute("SELECT * FROM execution_environments WHERE id='dev-gamma' FOR UPDATE").fetchone()
        if not row or row['state'] != 'interrupted' or lease['holder'] != args.run_id or lease['state'] != 'quarantined':
            raise RuntimeError('Only the existing quarantined holder can be recovered')
        child = row['body']['active_run_id']
        root = Path('/var/lib/pr-gamma-executor/diagnostics') / child
        cfg = json.loads((root / 'frozen-settings.json').read_text())
        owner = json.loads((root / 'ownership.json').read_text())
        if owner['run_id'] != child or owner['workspace_id'] != cfg['WORKSPACE_ID']:
            raise RuntimeError('Owned execution mismatch')
        if residual_processes(root, pwd.getpwnam('pr-e2e').pw_uid):
            raise RuntimeError('Old execution processes still exist')
        for path in Path('/proc').glob('[0-9]*/cmdline'):
            try:
                cmd = path.read_bytes().split(b'\0')
                if b'/usr/local/sbin/pr-gamma-execute' in cmd and args.run_id.encode() in cmd:
                    raise RuntimeError('Privileged executor still active')
            except (FileNotFoundError, ProcessLookupError):
                pass
        generation = lease['generation']
        def guard():
            current = db.execute("SELECT * FROM execution_environments WHERE id='dev-gamma'").fetchone()
            if current['holder'] != args.run_id or current['state'] != 'quarantined' or current['generation'] != generation:
                raise PermissionError('Recovery ownership lost')
        access.assert_dev_gamma()
        access.connect()
        archive = Path('/var/lib/pr-e2e-share/runs') / child
        report = json.loads((archive / 'run.json').read_text())
        if args.align_workspace:
            before = access.resource('deployment', 'multica-server')
            backup = root / ('recovery-config-before-' + str(int(time.time())) + '.json')
            backup.write_text(json.dumps(before))
            backup.chmod(0o600)
            containers = before['spec']['template']['spec']['containers']
            candidates = [i for i,c in enumerate(containers) if '/multica-server' in c['image']]
            if len(candidates) != 1:
                raise RuntimeError('Expected one Multica application container')
            index = candidates[0]
            env = containers[index].get('env', [])
            new_env = [entry for entry in env if entry['name'] != 'MULTICA_WORKSPACE_ID']
            new_env.append({'name': 'MULTICA_WORKSPACE_ID', 'value': cfg['WORKSPACE_ID']})
            operations = [{'op': 'test', 'path': '/metadata/uid', 'value': before['metadata']['uid']},
                          {'op': 'test', 'path': '/metadata/resourceVersion', 'value': before['metadata']['resourceVersion']},
                          {'op': 'add', 'path': f'/spec/template/spec/containers/{index}/env', 'value': new_env}]
            guard()
            access.remote('kubectl -n default patch deployment multica-server --type=json -p ' + shlex.quote(json.dumps(operations)))
            access.remote('kubectl -n default rollout status deployment/multica-server --timeout=240s', timeout=270)
            evidence['configuration_repair'] = {'name': 'MULTICA_WORKSPACE_ID', 'workspace_id': cfg['WORKSPACE_ID'], 'backup': str(backup)}
        archived_cleanup = report.get('cleanup') or {}
        if archived_cleanup.get('status') == 'passed' and not archived_cleanup.get('active_residuals'):
            result = archived_cleanup
            evidence['cleanup_source'] = 'verified_child_archive'
        else:
            services = access.resource('services')['items']
            router = next(s for s in services if s['spec'].get('selector', {}).get('app') == 'service-router')
            app = access.forward(router['spec']['clusterIP'], 80, 0)
            env = {**os.environ, 'E2E_APP_URL': app, 'HOME': str(root), 'PATH': '/opt/pr-pipeline-tools/bin:/usr/local/bin:/usr/bin:/bin'}
            result = cleanup(root, env, access, guard)
            evidence['cleanup_source'] = 'recovery_run'
        evidence['cleanup'] = result
        saved = root / ('recovery-' + str(int(time.time())) + '.json')
        saved.write_text(json.dumps(evidence, ensure_ascii=False))
        saved.chmod(0o600)
        print(json.dumps(evidence, ensure_ascii=False), flush=True)
        if result['status'] != 'passed' or result['active_residuals']:
            raise RuntimeError('Recovery cleanup incomplete; quarantine retained')
        hashes = report.get('archive_manifest', [])
        if not hashes or not all((archive / p['path']).resolve().is_relative_to(archive) and digest(archive / p['path']) == p['sha256'] for p in hashes):
            raise RuntimeError('Archive verification failed')
        ready = wait_for_deployments(access, {d['metadata']['name'] for d in access.resource('deployments')['items']})
        evidence.update(environment_health='ready', archive_verified=True, processes_reconciled=True,
                        remote_operations_reconciled=True, environment_unlocked=True, ready_deployments=len(ready),
                        operator_intervention=True)
        db.execute('INSERT INTO audit(run_id,kind,body) VALUES(%s,%s,%s)', (args.run_id, 'operator-cleanup-verified', Jsonb(evidence)))
    # The original attempt stays unsuccessful. Only evidence-gated recovery releases it.
    store.recover(args.run_id, evidence)
    print('RECOVERY_VERIFIED=' + args.run_id)
finally:
    access.close()
