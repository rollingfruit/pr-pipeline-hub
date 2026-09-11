"""Provider-acknowledged GitHub outbox; retries reconcile comments by marker."""
import json
import threading
import time
from control_client import rpc
from pr_pipeline_hub import redact


def send(hub, item):
    run = item['run']
    repo = run['repo']
    if item['channel'] == 'newlink':
        from newlink_delivery import send as send_newlink
        return send_newlink(hub,item)
    if run.get('stale') or run.get('status') in {'closed','superseded'}:
        state = 'error'
    elif item['phase'] == 'queued' and run['status'] in {'queued','running'}:
        state = 'pending'
    else:
        state = run.get('failure_kind') or ('success' if run.get('conclusion')=='success' else 'error')
    url = hub._run_web_url(hub.public_base_url,run['id'])
    if item['channel'] == 'github_status':
        context = 'newlink/e2e-local'
        # Reconcile an ambiguous successful POST before sending another status.
        statuses = hub._gh_json(['api', f"repos/{repo}/commits/{run['head_sha']}/statuses?per_page=100"])
        description = f"E2E {state}; run {run['id']}"
        previous = next((s for s in statuses if s['context']==context),None)
        if previous and previous['state']==state and previous.get('description')==description:
            return {'ok':True,'receipt_id':str(previous['id']),'state':state}
        result = hub._gh_json(['api',f"repos/{repo}/statuses/{run['head_sha']}",'-f',f'state={state}',
            '-f',f'context={context}','-f','description='+description,'-f','target_url='+url])
        return {'ok':True,'receipt_id':str(result['id']),'state':state}
    marker = f"<!-- pr-pipeline-hub:{run['id']} -->"
    review = run.get('review',{})
    body = '\n'.join([marker,'## PR Pipeline Hub · 观察模式',
        f"版本：`{run['head_sha']}` / base `{run.get('base_sha','')}`",
        f"测试：{run.get('summary','尚未完成')}，状态：{state}",
        '范围：'+', '.join(s['id'] for s in run.get('suites',[])),
        '代码风险：'+(review.get('summary','检视尚未完成，风险未知')),
        f'[流水线与证据]({url})',
        '此结果不代表已启用强制合入门禁；测试、检视、报告和群通知分别核对。'])
    pages = hub._gh_json(['api',f"repos/{repo}/issues/{run['pr_number']}/comments?per_page=100",'--paginate','--slurp'])
    identity = hub._gh_json(['api','user'])['id']
    previous = next((c for page in pages for c in page if marker in c.get('body','') and c.get('user',{}).get('id')==identity),None)
    if previous and previous['body']==body:
        return {'ok':True,'receipt_id':str(previous['id']),'url':previous['html_url']}
    endpoint = f"repos/{repo}/issues/comments/{previous['id']}" if previous else f"repos/{repo}/issues/{run['pr_number']}/comments"
    result = hub._gh_json(['api',endpoint,'--method','PATCH' if previous else 'POST','-f','body='+body])
    return {'ok':True,'receipt_id':str(result['id']),'url':result['html_url']}


def work(hub):
    while True:
        try:
            item = rpc('/internal/deliveries/claim',{})
            if item:
                try:
                    receipt = send(hub,item)
                except Exception as error:
                    receipt = {'ok':False,'error':redact(str(error))[:1000]}
                rpc(f"/internal/deliveries/{item['id']}/finish", {'attempts':item['attempts'],'receipt':receipt})
        except Exception as error:
            print('Delivery worker unavailable:',redact(str(error))[:200],flush=True)
        time.sleep(5)
