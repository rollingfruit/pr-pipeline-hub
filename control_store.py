"""Durable event inbox and single-slot, fenced review queue."""
import json
import secrets
from datetime import datetime, timezone
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

DDL = '''
CREATE TABLE IF NOT EXISTS repositories (id bigint PRIMARY KEY, name text UNIQUE NOT NULL, activated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS events (delivery text PRIMARY KEY, digest text NOT NULL, received_at timestamptz NOT NULL DEFAULT now(), payload jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS reviews (id text PRIMARY KEY, repo_id bigint NOT NULL, pr integer NOT NULL, head text NOT NULL,
 base text NOT NULL DEFAULT '', event_at timestamptz NOT NULL, state text NOT NULL, body jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 lease_token text, lease_until timestamptz, worker text);
ALTER TABLE reviews DROP CONSTRAINT IF EXISTS reviews_repo_id_pr_head_key;
CREATE INDEX IF NOT EXISTS review_version_lookup ON reviews(repo_id,pr,head,created_at DESC);
CREATE TABLE IF NOT EXISTS audit (seq bigserial PRIMARY KEY, run_id text NOT NULL, at timestamptz DEFAULT now(), kind text NOT NULL, body jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS deliveries (id bigserial PRIMARY KEY, run_id text NOT NULL, channel text NOT NULL,
 phase text NOT NULL, state text NOT NULL DEFAULT 'pending', attempts integer NOT NULL DEFAULT 0,
 next_attempt timestamptz NOT NULL DEFAULT now(), body jsonb NOT NULL DEFAULT '{}', UNIQUE(run_id,channel,phase));
CREATE TABLE IF NOT EXISTS pr_watermarks (repo_id bigint NOT NULL, pr integer NOT NULL, event_at timestamptz NOT NULL,
 closed boolean NOT NULL DEFAULT false, PRIMARY KEY(repo_id,pr));
CREATE TABLE IF NOT EXISTS monitors (id text PRIMARY KEY, body jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now());
'''


class Store:
    def __init__(self, dsn):
        self.dsn = dsn

    def db(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def initialize(self):
        with self.db() as db:
            db.execute(DDL)
            from batch_store import DDL as batch_ddl
            db.execute(batch_ddl)
            waiting=db.execute("UPDATE reviews SET state='awaiting_selection',body=body || %s WHERE state IN ('queued','draft') AND body->>'trigger_source' IN ('github_poll','github_webhook') RETURNING id",(Jsonb({'summary':'等待人工重新选择并提交联合验证','failure_kind':'error'}),)).fetchall()
            for row in waiting:
                db.execute("INSERT INTO deliveries(run_id,channel,phase) VALUES(%s,'github_status','final') ON CONFLICT DO NOTHING",(row['id'],))

    def repositories(self):
        with self.db() as db:
            return db.execute('SELECT id,name FROM repositories ORDER BY name').fetchall()

    def register(self, repo_id, name):
        with self.db() as db:
            db.execute('INSERT INTO repositories(id,name) VALUES(%s,%s) ON CONFLICT(id) DO UPDATE SET name=excluded.name', (repo_id, name))

    def receive(self, delivery, digest, event, payload, source='github_webhook'):
        repo_id = payload.get('repository', {}).get('id')
        with self.db() as db:
            repo = db.execute('SELECT * FROM repositories WHERE id=%s FOR UPDATE', (repo_id,)).fetchone()
            if not repo:
                raise PermissionError('Repository is not registered')
            previous = db.execute('SELECT digest FROM events WHERE delivery=%s', (delivery,)).fetchone()
            if previous:
                if previous['digest'] != digest:
                    raise ValueError('Delivery ID reused with different payload')
                pr = payload.get('pull_request', {})
                receipt = db.execute("SELECT a.run_id,r.state FROM audit a JOIN reviews r ON r.id=a.run_id WHERE a.body->>'delivery'=%s ORDER BY a.seq LIMIT 1", (delivery,)).fetchone()
                if receipt:
                    return {'duplicate': True, 'id': receipt['run_id'], 'status':receipt['state']}
                existing = db.execute('SELECT id FROM reviews WHERE repo_id=%s AND pr=%s AND head=%s ORDER BY created_at DESC LIMIT 1',
                    (repo_id,pr.get('number'),pr.get('head',{}).get('sha'))).fetchone()
                return {'duplicate': True, **({'id':existing['id']} if existing else {})}
            db.execute('INSERT INTO events(delivery,digest,payload) VALUES(%s,%s,%s)', (delivery,digest,Jsonb(payload)))
            if event == 'ping':
                return {'accepted': True}
            if event == 'push':
                branch = payload.get('ref', '').removeprefix('refs/heads/')
                db.execute("UPDATE reviews SET body=body || %s WHERE id IN (SELECT batch_id FROM batch_members WHERE repo_id=%s) AND EXISTS(SELECT 1 FROM jsonb_array_elements(body->'members') m WHERE m->>'base_ref'=%s AND (m->>'repo_id')::bigint=%s)", (Jsonb({'stale':True,'stale_reason':'目标分支更新'}),repo_id,branch,repo_id))
                db.execute("UPDATE reviews SET body=body || %s,updated_at=now() WHERE repo_id=%s AND body->>'base_ref'=%s", (Jsonb({'stale': True, 'stale_reason': '目标分支更新'}), repo_id, branch))
                return {'accepted': True}
            pr = payload.get('pull_request', {})
            number, head = pr.get('number', payload.get('number')), pr.get('head', {}).get('sha')
            if not isinstance(number, int) or not isinstance(head, str):
                raise ValueError('Invalid PR event')
            action = payload.get('action')
            when = datetime.fromisoformat(pr['updated_at'].replace('Z', '+00:00'))
            if when < repo['activated_at']:
                return {'ignored': 'before activation'}
            latest = db.execute('SELECT event_at,closed FROM pr_watermarks WHERE repo_id=%s AND pr=%s', (repo_id, number)).fetchone()
            if latest and (latest['event_at'] > when or (latest['closed'] and latest['event_at'] == when and action != 'reopened')):
                return {'ignored': 'out of order'}
            db.execute('INSERT INTO pr_watermarks(repo_id,pr,event_at,closed) VALUES(%s,%s,%s,%s) ON CONFLICT(repo_id,pr) DO UPDATE SET event_at=excluded.event_at,closed=excluded.closed', (repo_id,number,when,action=='closed'))
            if action == 'closed':
                db.execute("UPDATE reviews SET body=body || %s WHERE id IN (SELECT batch_id FROM batch_members WHERE repo_id=%s AND pr=%s)", (Jsonb({'stale':True,'stale_reason':'参与 PR 已关闭或合入'}),repo_id,number))
                db.execute("UPDATE reviews SET state=CASE WHEN state IN ('queued','draft') THEN 'closed' ELSE state END, body=body || %s,event_at=%s,updated_at=now() WHERE repo_id=%s AND pr=%s AND body->>'kind' IS DISTINCT FROM 'batch'", (Jsonb({'stale': True, 'pr_state': 'MERGED' if pr.get('merged') else 'CLOSED'}), when, repo_id, number))
                return {'accepted': True}
            if action not in {'opened', 'reopened', 'ready_for_review', 'synchronize'}:
                return {'ignored': 'action'}
            if source in {'github_webhook','github_poll'}:
                db.execute("UPDATE reviews SET body=body || %s WHERE id IN (SELECT batch_id FROM batch_members WHERE repo_id=%s AND pr=%s AND head<>%s)", (Jsonb({'stale':True,'stale_reason':'参与 PR 更新'}),repo_id,number,head))
                return {'accepted':True,'discovery_only':True}
            old = db.execute('SELECT id,state FROM reviews WHERE repo_id=%s AND pr=%s AND head=%s ORDER BY created_at DESC LIMIT 1', (repo_id, number, head)).fetchone()
            retry_of = None
            if source == 'local_manual' and payload.get('manual_retry') and old:
                if old['state'] not in {'completed','blocked'}:
                    raise ValueError('Only completed or blocked executions can be retried')
                retry_of, old = old['id'], None
            if old and not (old['state'] in {'draft', 'closed'} and action in {'ready_for_review', 'reopened'}):
                return {'id': old['id'], 'duplicate': True, 'status':old['state']}
            db.execute("UPDATE reviews SET state=CASE WHEN state IN ('queued','draft') THEN 'superseded' ELSE state END,body=body || %s WHERE repo_id=%s AND pr=%s AND head<>%s", (Jsonb({'stale': True}), repo_id, number, head))
            run_id = old['id'] if old else datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3)
            state = 'draft' if pr.get('draft') else 'queued'
            body = {'id': run_id, 'repo': repo['name'], 'pr_number': number, 'pr_url': pr['html_url'],
                    'title': pr['title'], 'head_sha': head, 'base_sha': pr['base']['sha'],
                    'head_ref': pr['head']['ref'], 'base_ref': pr['base']['ref'], 'profile': 'browser-e2e',
                    'status': state, 'requested_by': payload.get('sender', {}).get('login', 'github'),
                    'created_at': when.isoformat(), 'summary': '等待本地执行器', 'stages': [], 'suites': [],
                    'trigger_source':source, 'retry_of':retry_of,
                    'review': {'status': 'pending', 'findings': []}, 'github': {'state': 'pending', 'ok': False}}
            db.execute('INSERT INTO reviews(id,repo_id,pr,head,base,event_at,state,body) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET state=excluded.state,body=excluded.body,event_at=excluded.event_at', (run_id, repo_id, number, head, pr['base']['sha'], when, state, Jsonb(body)))
            db.execute('INSERT INTO audit(run_id,kind,body) VALUES(%s,%s,%s)', (run_id, source, Jsonb({'delivery': delivery, 'action': action})))
            for channel in ('newlink', 'github_status'):
                db.execute('INSERT INTO deliveries(run_id,channel,phase) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (run_id,channel,'queued'))
            return {'id': run_id, 'accepted': True, 'status':state}

    def set_monitor(self, name, body):
        with self.db() as db:
            db.execute('INSERT INTO monitors(id,body) VALUES(%s,%s) ON CONFLICT(id) DO UPDATE SET body=excluded.body,updated_at=now()', (name,Jsonb(body)))
        return {'ok':True}

    def monitors(self):
        with self.db() as db:
            rows=db.execute('SELECT id,body,updated_at FROM monitors ORDER BY id').fetchall()
        return [{**r['body'],'id':r['id'],'server_received_at':r['updated_at'].isoformat()} for r in rows]

    def runs(self, run_id=None):
        with self.db() as db:
            rows = db.execute('SELECT * FROM reviews WHERE (%s::text IS NULL OR id=%s) ORDER BY created_at DESC LIMIT 200', (run_id,run_id)).fetchall()
            deliveries = db.execute('SELECT run_id,channel,phase,state,attempts,body FROM deliveries WHERE run_id=ANY(%s) ORDER BY id', ([r['id'] for r in rows],)).fetchall()
            queued = [r['id'] for r in db.execute("SELECT id FROM reviews WHERE state='queued' ORDER BY created_at,id").fetchall()]
        return [{**r['body'], 'status': r['state'], 'queue_position': queued.index(r['id']) + 1 if r['id'] in queued else 0,
                 'deliveries': [{**d, **d['body'], 'provider_state':d['body'].get('state'), 'state':d['state'], 'ok': d['state']=='delivered'} for d in deliveries if d['run_id']==r['id']]} for r in rows]

    def recover(self, run_id, evidence):
        if not evidence.get('environment_unlocked') or not evidence.get('processes_reconciled'):
            raise ValueError('Explicit local environment reconciliation required')
        with self.db() as db:
            patch = {k:v for k,v in evidence.get('result',{}).items() if k in {'review','stages','error','failure_stage','test_results','suites','policy','merge_conflicts'}}
            patch.update(recovery={k:v for k,v in evidence.items() if k!='result'}, failure_kind='error',
                         conclusion='failure', summary='执行器中断后已核对释放环境；本次结果不可用于合入通过')
            row = db.execute("UPDATE reviews SET state='blocked',lease_token=NULL,body=body || %s WHERE id=%s AND state='interrupted' RETURNING id,body", (Jsonb(patch),run_id)).fetchone()
            if not row:
                raise ValueError('Run is not interrupted')
            db.execute('INSERT INTO audit(run_id,kind,body) VALUES(%s,%s,%s)', (run_id,'recovered',Jsonb(evidence)))
            if row['body'].get('kind')=='batch':
                from batch_store import enqueue_deliveries
                enqueue_deliveries(db,row['body'],'final')
            else:
                for channel in ('github_status','github_comment','newlink'):
                    db.execute('INSERT INTO deliveries(run_id,channel,phase) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (run_id,channel,'final'))
        return {'ok': True}

    def claim_delivery(self):
        with self.db() as db:
            db.execute("""UPDATE deliveries d SET state='superseded' FROM reviews r
                WHERE d.run_id=r.id AND d.channel LIKE 'batch_status:%%' AND d.state IN ('pending','retry')
                AND EXISTS(SELECT 1 FROM reviews newer WHERE newer.body->>'kind'='batch'
                    AND newer.body->>'combination_key'=r.body->>'combination_key'
                    AND newer.created_at>r.created_at)""")
            db.execute("""UPDATE deliveries d SET state='superseded' FROM reviews r
                WHERE d.run_id=r.id AND d.channel='github_status' AND d.state IN ('pending','retry')
                AND EXISTS(SELECT 1 FROM reviews newer WHERE newer.repo_id=r.repo_id AND newer.pr=r.pr
                    AND newer.head=r.head AND newer.created_at>r.created_at)""")
            row = db.execute("SELECT * FROM deliveries WHERE state IN ('pending','retry') AND next_attempt<=now() ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
            if not row:
                return None
            generation = row['attempts'] + 1
            db.execute("UPDATE deliveries SET attempts=%s,state='retry',next_attempt=now()+interval '120 seconds' WHERE id=%s", (generation,row['id']))
            run = db.execute('SELECT body,state FROM reviews WHERE id=%s', (row['run_id'],)).fetchone()
            return {**row,'attempts':generation,'run':{**run['body'],'status':run['state']}}

    def finish_delivery(self, delivery_id, generation, receipt):
        ok = receipt.get('ok') is True
        if ok and not receipt.get('receipt_id'):
            raise ValueError('A real provider receipt ID is required')
        with self.db() as db:
            row = db.execute("UPDATE deliveries SET state=%s,body=%s,next_attempt=now()+interval '5 minutes' WHERE id=%s AND attempts=%s RETURNING id", ('delivered' if ok else 'retry',Jsonb(receipt),delivery_id,generation)).fetchone()
            if not row:
                raise PermissionError('Stale delivery attempt')
        return {'ok': True}

    def claim(self, worker, repositories=None):
        with self.db() as db:
            db.execute('SELECT pg_advisory_xact_lock(91807912)')
            # Expiration needs explicit recovery; do not run another environment alongside an orphan.
            db.execute("UPDATE reviews SET state='interrupted',body=body || %s WHERE state='running' AND lease_until<now()", (Jsonb({'summary': '执行器心跳超时，需恢复确认', 'failure_kind': 'error'}),))
            if db.execute("SELECT id FROM reviews WHERE state IN ('running','interrupted') LIMIT 1").fetchone():
                return None
            row = db.execute("SELECT * FROM reviews WHERE state='queued' AND (body->>'kind'='batch' OR %s::text[] IS NULL OR lower(body->>'repo')=ANY(%s::text[])) ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1", (repositories, repositories)).fetchone()
            if not row:
                return None
            token = secrets.token_urlsafe(32)
            db.execute("UPDATE reviews SET state='running',lease_token=%s,lease_until=now()+interval '180 seconds',worker=%s WHERE id=%s", (token, worker, row['id']))
            return {'run': row['body'], 'lease_token': token}

    def update(self, run_id, token, patch, final=False):
        if not isinstance(patch, dict):
            raise ValueError('Invalid progress')
        with self.db() as db:
            row = db.execute('SELECT * FROM reviews WHERE id=%s FOR UPDATE', (run_id,)).fetchone()
            if not row or row['state'] != 'running' or row['lease_until'] <= datetime.now(timezone.utc) or not secrets.compare_digest(row['lease_token'] or '', token):
                raise PermissionError('Invalid or expired execution lease')
            patch = {k:v for k,v in patch.items() if k not in {'id','repo','pr_number','pr_url','created_at','head_sha','base_sha'}}
            if row['body'].get('stale'):
                patch['stale'] = True
            status = patch.get('status', 'completed') if final else 'running'
            if final and status not in {'completed','blocked','interrupted'}:
                raise ValueError('Invalid final state')
            db.execute("UPDATE reviews SET body=body || %s,state=%s,lease_until=now()+interval '180 seconds',updated_at=now() WHERE id=%s", (Jsonb(patch),status,run_id))
            if final:
                if row['body'].get('kind')=='batch':
                    from batch_store import enqueue_deliveries
                    enqueue_deliveries(db,row['body'],'final')
                else:
                    for channel in ('github_status','github_comment','newlink'):
                        db.execute('INSERT INTO deliveries(run_id,channel,phase) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (run_id,channel,'final'))
            return {'ok': True, 'stale': bool(row['body'].get('stale'))}
