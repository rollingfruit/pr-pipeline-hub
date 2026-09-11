"""Trusted batch manifest validation and local GitHub resolution."""
import hashlib
import json
import re
import threading
from urllib.parse import quote
from e2e_catalog import CORE, select_suites

SUPPORTED = ('agent-governance-gw','multica-aiwelink','service_router','AgentLink','skills-market','CellMem','semantic-schedule','semantic-gateway','aiwelink-temporal')
SUBMIT_LOCK = threading.Lock()


def validate(body):
    from cloud_config import enabled
    for field,feature in (('codex_review','code_review'),('github_write','github_write')):
        if body.get(field) and not enabled(feature):raise ValueError('该可选环节未启用：'+field)
    if type(body.get('approve_risky',False)) is not bool:
        raise ValueError('构建确认必须为布尔值')
    members=body.get('members',[])
    if not isinstance(members,list) or not 1<=len(members)<=len(SUPPORTED):
        raise ValueError('请选择至少一个 PR')
    seen=set()
    for m in members:
        if m.get('repo') not in ['rollingfruit/'+n for n in SUPPORTED]:
            raise ValueError('仓库尚无候选构建映射')
        if m['repo'] in seen:
            raise ValueError('同仓最多选择一个 PR')
        seen.add(m['repo'])
        branch = body.get('source_mode') == 'branch'
        if branch:
            if type(m.get('repo_id')) is not int or not m.get('head_ref') or not m.get('base_ref') or m.get('pr_number') is not None:
                raise ValueError('Invalid branch identity')
            if body.get('github_write') or body.get('codex_review'):
                raise ValueError('Branch batches do not enable PR review/writeback')
        elif type(m.get('repo_id')) is not int or type(m.get('pr_number')) is not int or m['pr_number']<1:
            raise ValueError('Invalid repository / PR identity')
        if not branch and m.get('pr_url')!=f"https://github.com/{m['repo']}/pull/{m['pr_number']}":
            raise ValueError('PR URL does not match identity')
        for key in ('head_sha','base_sha'):
            if not re.fullmatch('[0-9a-f]{40}',m.get(key,'')):
                raise ValueError('Missing frozen SHA')
    if not isinstance(body.get('suite_ids'),list) or not body['suite_ids']:
        raise ValueError('请选择非空的已实现用例集合')
    suites,full=select_suites('',0,body['suite_ids'])
    for key in ('codex_review','baseline_enabled','github_write'):
        if type(body.get(key)) is not bool:
            raise ValueError('Invalid execution option: '+key)
    if not isinstance(body.get('name'),str) or not body['name'].strip() or len(body['name'])>120:
        raise ValueError('批次名称不能为空且最多120字')
    if not re.fullmatch('[A-Za-z0-9-]{8,100}',body.get('submission_id','')):
        raise ValueError('Invalid submission ID')
    return suites, full and body['baseline_enabled']


def fingerprint(body):
    return hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def resolve(hub, urls):
    from pr_pipeline_hub import parse_pr_url, utc_now, redact
    if not isinstance(urls,list) or not 1<=len(urls)<=30:
        raise ValueError('请输入1至30个 PR 链接')
    results=[]
    for url in urls:
        try:
            owner,name,number=parse_pr_url(url)
            if owner!='rollingfruit' or name not in SUPPORTED:
                results.append({'url':url,'ok':False,'code':'unsupported','error':'仓库尚无候选构建映射'});continue
            repo=f'{owner}/{name}'
            p=hub._gh_json(['api',f'repos/{repo}/pulls/{number}'])
            if p['state']!='open' or p.get('merged_at') or p.get('draft'):
                code='merged' if p.get('merged_at') else 'closed' if p['state']!='open' else 'draft'
                results.append({'url':url,'ok':False,'code':code,'error':'PR 已合入' if code=='merged' else 'PR 已关闭' if code=='closed' else 'PR 仍为草稿'});continue
            base=hub._gh_json(['api',f"repos/{repo}/git/ref/heads/{quote(p['base']['ref'],safe='')}"])['object']['sha']
            pages=hub._gh_json(['api',f'repos/{repo}/pulls/{number}/files?per_page=100','--paginate','--slurp'])
            files=sorted({n for page in pages for f in page for n in (f['filename'],f.get('previous_filename')) if n})
            from review_policy import select
            results.append({'url':url,'ok':True,'member':{'repo':repo,'repo_id':p['base']['repo']['id'],
                'pr_number':number,'pr_url':f'https://github.com/{repo}/pull/{number}','title':p['title'],
                'head_sha':p['head']['sha'],'base_sha':base,'base_ref':p['base']['ref'],'head_ref':p['head']['ref'],
                'checked_at':utc_now(),'changed_files':files,'risky_files':select(repo,files)['risky_files']}})
        except ValueError as e:
            results.append({'url':url,'ok':False,'code':'invalid_link','error':str(e)})
        except Exception as e:
            message=redact(str(e))[:400]
            results.append({'url':url,'ok':False,'code':'permission' if any(s in message for s in ('401','403','404')) else 'network','error':message})
    return results


def submit(hub,body):
    with SUBMIT_LOCK:
        return _submit(hub,body)


def _submit(hub,body):
    from control_client import rpc
    from e2e_runner import load_stack
    validate(body)
    # Retry an identical HTTP submission even if the PR has since moved.
    cache=hub.runs_dir.parent/'batch-submissions'
    cache.mkdir(exist_ok=True)
    file=cache/(body['submission_id']+'.json')
    digest=fingerprint(body)
    if file.exists():
        saved=json.loads(file.read_text())
        if saved['digest']!=digest:raise ValueError('提交标识已用于不同内容')
        return rpc('/internal/batches',saved['manifest'])
    if body.get('source_mode')=='branch':
        from branch_batches import resolve as resolve_branches
        fresh=resolve_branches(hub,body['members'])
    else:
        fresh=resolve(hub,[m['pr_url'] for m in body['members']])
    for expected,result in zip(body['members'],fresh):
        if not result['ok']:raise ValueError(result['error'])
        actual=result['member']
        if any(expected[k]!=actual[k] for k in ('repo_id','head_sha','base_sha')):
            raise ValueError('版本已过期，请重新解析：'+expected['repo'])
        if actual['risky_files'] and not body.get('approve_risky',False):
            raise ValueError('构建敏感变更需本机确认：'+', '.join(actual['risky_files']))
    stack=load_stack();preflight=stack.doctor(include_runtime=False)
    if not preflight['ok']:
        raise ValueError('环境检查失败：'+'; '.join(c['name'] for c in preflight['checks'] if c.get('required',True) and not c['ok']))
    manifest={**body,'members':[r['member'] for r in fresh],'baseline_revisions':preflight['revisions']}
    if body.get('source_mode')=='branch':
        import os
        from pathlib import Path
        baseline=Path(os.environ.get('GAMMA_E2E_BASELINE_FILE','/etc/pr-e2e/artifact-baseline.json'))
        if baseline.is_file():
            manifest['integration_images']=json.loads(baseline.read_text())
            for item in manifest['integration_images'].values():
                manifest['baseline_revisions'][item['repo'].split('/')[-1]]=item['source_sha']
    from pr_pipeline_hub import atomic_json
    atomic_json(file,{'digest':digest,'manifest':manifest})
    return rpc('/internal/batches',manifest)
