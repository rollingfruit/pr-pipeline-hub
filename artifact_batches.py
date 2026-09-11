"""Authenticated, immutable Robot CI build handoff into the existing queue."""
import hashlib
import json
import re
from datetime import datetime, timezone
from psycopg.types.json import Jsonb
from e2e_catalog import CATALOG

SHA = re.compile(r'^[0-9a-f]{40}$')
DIGEST = re.compile(r'^sha256:[0-9a-f]{64}$')
SAFE = re.compile(r'^[a-zA-Z0-9_-]{1,120}$')


def validate(body):
    if not isinstance(body,dict):raise ValueError('Build manifest must be an object')
    if body.get('schema_version') != 1 or not re.fullmatch(r'[A-Za-z0-9-]{1,110}', body.get('build_id', '')):
        raise ValueError('Invalid build manifest identity')
    if body.get('target') != 'ci-compose':
        raise ValueError('Only isolated CI Compose is supported')
    suites = body.get('suite_ids')
    implemented = {s['id']: s for s in CATALOG if s['implemented']}
    if not isinstance(suites, list) or not suites or len(set(suites)) != len(suites) or any(s not in implemented for s in suites):
        raise ValueError('Select a nonempty implemented suite set')
    if not isinstance(body.get('baseline_enabled'), bool):
        raise ValueError('Explicit baseline option required')
    baseline, candidates = body.get('baseline_images'), body.get('candidate_images')
    if not isinstance(baseline, dict) or not baseline or not isinstance(candidates, dict) or not candidates:
        raise ValueError('Complete baseline and candidate manifests required')
    for group in (baseline, candidates):
        for service, item in group.items():
            if not isinstance(item,dict):raise ValueError('Image manifest must be an object')
            if not SAFE.fullmatch(service) or not SHA.fullmatch(item.get('source_sha', '')) or not DIGEST.fullmatch(item.get('image_id', '')):
                raise ValueError('Invalid source/image identity')
            if not re.fullmatch(r'rollingfruit/[A-Za-z0-9_-]+', item.get('repo', '')):
                raise ValueError('Invalid repository')
    if not set(candidates).issubset(baseline):
        raise ValueError('Candidate service missing from integration baseline')
    for service, item in candidates.items():
        if item['repo'] != baseline[service]['repo']:
            raise ValueError('Candidate repository mismatch')
        if not re.fullmatch(r'[0-9a-f]{64}', item.get('archive_sha256', '')) or not SAFE.fullmatch(item.get('archive_name', '').removesuffix('.tar')) or not item['archive_name'].endswith('.tar'):
            raise ValueError('Invalid immutable image archive')
    return [implemented[s] for s in suites]


def create(store, body):
    suites = validate(body)
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    run_id = 'gamma-' + body['build_id']
    now = datetime.now(timezone.utc).isoformat()
    members = [{'repo':m['repo'], 'head_sha':m['source_sha'], 'base_sha':body['baseline_images'][s]['source_sha'],
                'head_ref':m.get('branch',''), 'pr_number':None, 'pr_url':None} for s,m in body['candidate_images'].items()]
    first = members[0]
    run = {**first, 'id':run_id,'kind':'batch','source_mode':'artifact','profile':'browser-e2e',
           'title':'Gamma · '+body['build_id'],'created_at':now,'status':'queued','stages':[],
           'summary':'等待 CI 隔离 E2E','requested_by':'robot-ci','trigger_source':'robot_ci',
           'suites':suites,'full_acceptance':False,'members':members,'artifact_manifest':body,
           'baseline_revisions':{v['repo'].split('/')[-1]:v['source_sha'] for v in body['baseline_images'].values()},
           'options':{'codex_review':False,'github_write':False,'baseline_enabled':body['baseline_enabled']},
           'review':{'status':'disabled','summary':'构建产物验证，未启用代码检视','findings':[]},
           'approved_risky':False,'combination_key':digest[:12],'build_id':body['build_id'],
           'build_url':'http://119.8.233.58/#/build/'+first['repo'].split('/')[-1]}
    with store.db() as db:
        db.execute('SELECT pg_advisory_xact_lock(91807912)')
        old=db.execute('SELECT body FROM reviews WHERE id=%s',(run_id,)).fetchone()
        if old:
            if old['body'].get('artifact_manifest')!=body:raise ValueError('Build identity reused with different artifacts')
            return {'id':run_id,'duplicate':True,'web_path':'/batches/'+run_id}
        repo=db.execute('SELECT id FROM repositories WHERE name=%s',(first['repo'],)).fetchone()
        if not repo:raise ValueError('Repository not registered')
        # Zero is a storage sentinel only; the public record has no PR identity.
        db.execute('INSERT INTO reviews(id,repo_id,pr,head,base,event_at,state,body) VALUES(%s,%s,0,%s,%s,%s,%s,%s)',
                   (run_id,repo['id'],first['head_sha'],first['base_sha'],now,'queued',Jsonb(run)))
    return {'id':run_id,'status':'queued','web_path':'/batches/'+run_id}
