"""Batch metadata shares the existing fenced reviews queue."""
import json
from datetime import datetime, timezone
from psycopg.types.json import Jsonb
from batches import validate, fingerprint

DDL='''
CREATE TABLE IF NOT EXISTS batches (id text PRIMARY KEY REFERENCES reviews(id), submission_id text UNIQUE NOT NULL, digest text NOT NULL);
CREATE TABLE IF NOT EXISTS batch_members (batch_id text REFERENCES batches(id), repo_id bigint NOT NULL, pr integer NOT NULL, head text NOT NULL, base text NOT NULL, PRIMARY KEY(batch_id,repo_id));
ALTER TABLE reviews ALTER COLUMN pr DROP NOT NULL;
ALTER TABLE batch_members ALTER COLUMN pr DROP NOT NULL;
'''


def create(store, body):
    suites,full=validate(body)
    digest=fingerprint(body)
    run_id='batch-'+body['submission_id']
    now=datetime.now(timezone.utc).isoformat()
    first=body['members'][0]
    run={**first,'id':run_id,'kind':'batch','title':body['name'],'created_at':now,'status':'queued',
         'summary':'等待 CI 联合验证','profile':'browser-e2e','source_mode':body.get('source_mode','merge'),'trigger_source':'manual_batch',
         'requested_by':body.get('requested_by','local-selection'),'stages':[],'suites':suites,'full_acceptance':full,
         'members':body['members'],'baseline_revisions':body['baseline_revisions'],
         'integration_images':body.get('integration_images',{}),
         'options':{k:body[k] for k in ('codex_review','baseline_enabled','github_write')},
         'review':{'status':'pending' if body['codex_review'] else 'disabled','summary':'检视尚未完成' if body['codex_review'] else '未启用代码检视，代码风险未评估','findings':[]},
         'approved_risky':body.get('approve_risky',False),'combination_key':fingerprint({'members':[(m['repo_id'],m['pr_number'],m['head_sha'],m['base_sha']) for m in sorted(body['members'],key=lambda x:x['repo'])], 'suites':sorted(body['suite_ids']),'baseline':body['baseline_enabled'],'integration_revisions':body['baseline_revisions']})[:12]}
    with store.db() as db:
        db.execute('SELECT pg_advisory_xact_lock(91807912)')
        old=db.execute('SELECT * FROM batches WHERE submission_id=%s',(body['submission_id'],)).fetchone()
        if old:
            if old['digest']!=digest:raise ValueError('Submission ID reused')
            return {'id':old['id'],'duplicate':True,'web_path':'/batches/'+old['id']}
        previous=db.execute("SELECT id,body FROM reviews WHERE body->>'kind'='batch' AND body->>'combination_key'=%s ORDER BY created_at DESC LIMIT 1",(run['combination_key'],)).fetchone()
        run['attempt']=previous['body'].get('attempt',1)+1 if previous else 1
        run['retry_of']=previous['id'] if previous else None
        for m in body['members']:
            row=db.execute('SELECT name FROM repositories WHERE id=%s',(m['repo_id'],)).fetchone()
            if not row or row['name']!=m['repo']:raise ValueError('Repository identity not registered')
        db.execute('INSERT INTO reviews(id,repo_id,pr,head,base,event_at,state,body) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                   (run_id,first['repo_id'],first['pr_number'],first['head_sha'],first['base_sha'],now,'queued',Jsonb(run)))
        db.execute('INSERT INTO batches VALUES(%s,%s,%s)',(run_id,body['submission_id'],digest))
        for m in body['members']:
            db.execute('INSERT INTO batch_members VALUES(%s,%s,%s,%s,%s)',(run_id,m['repo_id'],m['pr_number'],m['head_sha'],m['base_sha']))
        enqueue_deliveries(db,run,'queued')
    return {'id':run_id,'status':'queued','web_path':'/batches/'+run_id}


def enqueue_deliveries(db,run,phase):
    if not run['options']['github_write']:return
    for m in run['members']:
        for kind in ('status','comment') if phase=='final' else ('status',):
            db.execute('INSERT INTO deliveries(run_id,channel,phase) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
                       (run['id'],f"batch_{kind}:{m['repo_id']}",phase))
