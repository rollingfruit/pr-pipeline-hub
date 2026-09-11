"""Single local runner. Never continues an execution after losing its lease."""
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from control_client import rpc
from pr_pipeline_hub import parse_pr_url, utc_now


def submit(hub, url, actor, profile, suites, diagnostic, request_id, source_mode):
    if diagnostic or source_mode != 'merge' or profile != 'browser-e2e':
        raise ValueError('ECS observation queue currently accepts full browser-e2e merge runs only; use the explicit diagnostic runner for debug')
    owner, repo, number = parse_pr_url(url)
    if f'{owner}/{repo}'.lower() not in hub.allowed_repos:
        raise PermissionError('Repository not enabled')
    metadata = hub._gh_json(['api', f'repos/{owner}/{repo}/pulls/{number}'])
    if metadata['state'] != 'open':
        raise ValueError('PR must be open')
    event = {'action':'synchronize', 'repository':metadata['base']['repo'], 'pull_request':metadata,
             'sender':{'login':actor}}
    if request_id.startswith('retry-'):
        event['manual_retry'] = True
    from pr_pipeline_hub import atomic_json
    from urllib.parse import quote
    ref = hub._gh_json(['api', f"repos/{owner}/{repo}/git/ref/heads/{quote(metadata['base']['ref'], safe='')}"])
    event['pull_request']['base']['sha'] = ref['object']['sha']
    if metadata.get('draft'):
        raise ValueError('Draft PR is not ready for execution')
    # Keep retries byte-identical, including the manual activation timestamp.
    key = hashlib.sha256((request_id or f'{owner}/{repo}/{number}/{metadata["head"]["sha"]}/{ref["object"]["sha"]}').encode()).hexdigest()
    saved = hub.runs_dir.parent / 'submissions' / (key + '.json')
    if saved.exists():
        payload = json.loads(saved.read_text())
        old = payload['event']['pull_request']
        if old['html_url'] != metadata['html_url'] or old['head']['sha'] != metadata['head']['sha'] or old['base']['sha'] != ref['object']['sha']:
            raise ValueError('Submission identity reused for another PR version')
    else:
        event['pull_request']['updated_at'] = utc_now()
        digest = hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
        payload = {'delivery': 'local-'+key, 'digest': digest, 'event': event}
        atomic_json(saved, payload)
    result = rpc('/internal/submit', payload)
    if not result.get('id'):
        raise RuntimeError('Submission not queued: '+json.dumps(result))
    return {**result, 'status':result.get('status','queued'), 'web_url':hub._run_web_url(hub.public_base_url,result['id'])}


def work(hub):
    from github_deliveries import work as deliver
    from cloud_config import enabled
    if enabled('github_write'):
        threading.Thread(target=deliver,args=(hub,),daemon=True,name='delivery-worker').start()
    while True:
        try:
            from resource_gate import inspect
            resource=inspect()
            if resource.get('enabled'):
                rpc('/internal/worker-state',{'worker':os.environ.get('PIPELINE_WORKER_ID','ci-e2e'),'resource':resource})
                if not resource['ready']:
                    time.sleep(20)
                    continue
            claim = rpc('/internal/claim', {'worker':os.environ.get('PIPELINE_WORKER_ID','local-wsl'), 'repositories':sorted(hub.allowed_repos)})
            if claim:
                execute(hub, claim)
        except Exception as error:
            print('Control worker unavailable:', str(error)[:300], flush=True)
        time.sleep(10)


def execute(hub, claim):
    source, lease = claim['run'], claim['lease_token']
    run_id = source['id']
    hub.create_run(source.get('pr_url') or '',source['requested_by'],hub.public_base_url,
                   profile='browser-e2e',suites=[s['id'] for s in source.get('suites',[])] or None,_control_run=source)
    run = hub.runs[run_id]
    if source.get('kind')=='batch':
        run['source_mode']=source.get('source_mode','merge')
        run['integration_images']=source.get('integration_images',{})
        if run['source_mode']=='branch':
            hub._stage(run,'resolve')['name']='核验冻结分支版本'
            hub._stage(run,'snapshot')['name']='检出分支与固定依赖镜像'
        run.update({k:source[k] for k in ('kind','members','options','baseline_revisions','title','full_acceptance','approved_risky','combination_key')})
        run['review']=source['review']
        if source.get('source_mode')=='artifact':
            run.update({k:source[k] for k in ('source_mode','artifact_manifest','build_id','build_url')})
            run.update(head_sha=source['head_sha'],base_sha=source['base_sha'])
            for name,label in {'resolve':'核验构建产物','snapshot':'冻结镜像与校验归档','build':'导入确切镜像','deploy':'部署联合镜像（CI 隔离环境）'}.items():
                hub._stage(run,name)['name']=label
        if not source['options']['codex_review']:
            hub._stage(run,'agent').update(status='completed',conclusion='skipped',name='Codex 代码检视（未启用）')
        hub._save(run)
    stopped = threading.Event()
    lease_lost = threading.Event()
    run['_lease_lost'] = False

    def update(final=False):
        patch = hub.public_run(run)
        for key in ('web_url','local_url','_lease_lost'):
            patch.pop(key,None)
        return rpc(f"/internal/runs/{run_id}/{'finish' if final else 'progress'}", {'lease_token':lease, 'patch':patch})

    def heartbeat():
        last_ack = time.monotonic()
        while not stopped.wait(10):
            try:
                result = update()
                last_ack = time.monotonic()
                if result.get('stale'):
                    run['stale'] = True
            except Exception as error:
                from pr_pipeline_hub import redact
                with (hub.runs_dir/run_id/'worker.log').open('a') as log:
                    log.write(utc_now()+' heartbeat: '+redact(str(error))[:600]+'\n')
                if '409' in str(error) or time.monotonic()-last_ack >= 120:
                    lease_lost.set()
                    run['_lease_lost'] = True
                    return
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        update()
        try:
            hub._execute(run_id)
        except Exception as error:
            hub._fail_run(run_id, 'Worker execution failed: '+str(error)[:300])
            run['failure_kind'] = 'error'
    finally:
        stopped.set()
        thread.join(timeout=50)
    if lease_lost.is_set():
        run['status'] = 'interrupted'
        run['summary'] = '控制面租约丢失，需要本地恢复确认；未发送完成回写'
        hub._save(run)
        return
    try:
        update(final=True)
    except Exception as error:
        from pr_pipeline_hub import redact
        run.update(status='interrupted', summary='完成结果同步失败，需要本地恢复确认',
                   control_error=redact(str(error))[:600])
        hub._save(run)
