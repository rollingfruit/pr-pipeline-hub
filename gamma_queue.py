"""Gamma jobs share the review queue, with an additional fenced environment lease."""
import hashlib
import json
import re
import secrets
from datetime import datetime, timezone


DDL = '''
ALTER TABLE reviews ALTER COLUMN repo_id DROP NOT NULL;
ALTER TABLE reviews ALTER COLUMN pr DROP NOT NULL;
CREATE TABLE IF NOT EXISTS gamma_submissions (
 submission_id text PRIMARY KEY, digest text NOT NULL, run_id text UNIQUE NOT NULL REFERENCES reviews(id));
CREATE TABLE IF NOT EXISTS execution_environments (
 id text PRIMARY KEY, generation bigint NOT NULL DEFAULT 0,
 holder text REFERENCES reviews(id), lease_token text, lease_until timestamptz,
 state text NOT NULL DEFAULT 'idle', reason text NOT NULL DEFAULT '');
INSERT INTO execution_environments(id) VALUES ('dev-gamma') ON CONFLICT DO NOTHING;
'''
SUITES = ('E01', 'E02', 'E03', 'E04', 'E05', 'E06')


def validate(body):
    if not isinstance(body, dict):
        raise ValueError('Gamma submission must be an object')
    for key in ('submission_id', 'environment_id'):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(body.get(key, ''))):
            raise ValueError('Invalid ' + key)
    mode = body.get('mode', 'test')
    if mode not in ('test', 'deploy', 'stability'):
        raise ValueError('Unknown Gamma mode')
    suites = body.get('suite_ids', [])
    if not isinstance(suites, list) or any(s not in SUITES for s in suites) or len(set(suites)) != len(suites):
        raise ValueError('Invalid Gamma suites')
    if mode != 'deploy' and not suites:
        raise ValueError('Test suites must not be empty')
    if mode == 'deploy' and suites:
        raise ValueError('Deploy-only jobs cannot claim test coverage')
    if mode == 'stability' and (suites != list(SUITES) or type(body.get('rounds')) is not int
                              or body['rounds'] not in (10, 30)):
        raise ValueError('Stability acceptance requires 10 or 30 rounds of E01-E06')
    manifest = body.get('build_manifest')
    if mode == 'deploy' and not manifest:
        raise ValueError('Deploy-only requires an immutable build manifest')
    if manifest and not re.fullmatch(r'/var/lib/pr-e2e/build-inbox/[A-Za-z0-9_-]+\.json', manifest):
        raise ValueError('Private build manifest required')
    if manifest and not re.fullmatch(r'[0-9a-f]{64}', str(body.get('build_manifest_sha256', ''))):
        raise ValueError('Frozen build manifest digest required')
    return {k: body[k] for k in ('submission_id', 'environment_id', 'suite_ids')}, mode


def submit(store, body):
    from psycopg.types.json import Jsonb
    identity, mode = validate(body)
    payload = {**identity, 'mode': mode, 'rounds': body['rounds'] if mode == 'stability' else 1,
               'build_manifest': body.get('build_manifest'), 'build_manifest_sha256': body.get('build_manifest_sha256'),
               'requested_by': str(body.get('requested_by', 'robot-ci'))[:120]}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    run_id = 'gamma-' + secrets.token_hex(12)
    now = datetime.now(timezone.utc).isoformat()
    run = {'id': run_id, 'kind': 'gamma', 'source_mode': 'environment', 'repo': 'dev-gamma',
           'title': f"dev-gamma {payload['rounds']}轮稳定性验收" if mode == 'stability' else 'dev-gamma 部署与验证',
           'requested_by': payload['requested_by'], 'created_at': now, 'status': 'queued',
           'summary': '等待 dev-gamma 环境', 'environment_key': 'dev-gamma',
           'gamma_request': payload, 'rounds': [], 'target_rounds': payload['rounds'],
           'profile': 'browser-e2e', 'diagnostic': True, 'full_acceptance': False,
           'stages': [], 'pr_number': None, 'pr_url': None,
           'suites': [{'id': s, 'name': s} for s in identity['suite_ids']],
           'github': {'state': 'disabled'}, 'review': {'status': 'disabled', 'findings': []},
           'cleanup': {'status': 'pending'}, 'publication': {'status': 'pending'}}
    with store.db() as db:
        db.execute('SELECT pg_advisory_xact_lock(91807912)')
        old = db.execute('SELECT * FROM gamma_submissions WHERE submission_id=%s', (identity['submission_id'],)).fetchone()
        if old:
            if old['digest'] != digest:
                raise ValueError('Submission ID reused for different inputs')
            return {'id': old['run_id'], 'duplicate': True, 'web_path': '/runs/' + old['run_id']}
        db.execute("INSERT INTO reviews(id,repo_id,pr,head,base,event_at,state,body) VALUES(%s,NULL,NULL,'','',%s,'queued',%s)",
                   (run_id, now, Jsonb(run)))
        db.execute('INSERT INTO gamma_submissions VALUES(%s,%s,%s)', (identity['submission_id'], digest, run_id))
    return {'id': run_id, 'status': 'queued', 'web_path': '/runs/' + run_id}


def acquire(db, row, token):
    env = db.execute("SELECT * FROM execution_environments WHERE id='dev-gamma' FOR UPDATE").fetchone()
    if env['state'] != 'idle' or env['holder']:
        return None
    env = db.execute("UPDATE execution_environments SET holder=%s,lease_token=%s,lease_until=now()+interval '180 seconds',generation=generation+1,state='running',reason='' WHERE id='dev-gamma' RETURNING generation", (row['id'], token)).fetchone()
    return env['generation']


def assert_lease(db, run_id, token, generation=None):
    row = db.execute("SELECT e.*,r.state AS run_state,r.lease_token AS run_token,r.lease_until AS run_until FROM execution_environments e JOIN reviews r ON r.id=e.holder WHERE e.id='dev-gamma' FOR UPDATE OF e,r").fetchone()
    now = datetime.now(timezone.utc)
    if (not row or row['holder'] != run_id or row['state'] != 'running' or row['run_state'] != 'running'
            or row['lease_until'] <= now or row['run_until'] <= now
            or not secrets.compare_digest(row['lease_token'] or '', token)
            or not secrets.compare_digest(row['run_token'] or '', token)
            or (generation is not None and row['generation'] != generation)):
        raise PermissionError('Gamma environment lease is invalid; recovery required')
    return row


def check(store, run_id, token, generation):
    with store.db() as db:
        row = assert_lease(db, run_id, token, generation)
        return {'ok': True, 'generation': row['generation']}


def update_environment(db, run_id, token, patch, final):
    assert_lease(db, run_id, token)
    if not final:
        db.execute("UPDATE execution_environments SET lease_until=now()+interval '180 seconds' WHERE id='dev-gamma'")
        return
    clean = (patch.get('cleanup', {}).get('status') == 'passed'
             and patch.get('cleanup', {}).get('active_residuals') == []
             and patch.get('environment_health') == 'ready')
    if clean:
        db.execute("UPDATE execution_environments SET holder=NULL,lease_token=NULL,lease_until=NULL,state='idle',reason='' WHERE id='dev-gamma'")
    else:
        db.execute("UPDATE execution_environments SET state='quarantined',reason='Recovery/cleanup evidence required' WHERE id='dev-gamma'")
        patch['status'] = 'interrupted'
