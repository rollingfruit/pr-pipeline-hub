"""On-demand branch discovery and immutable branch identities, without PR scans."""
from urllib.parse import quote
from batches import SUPPORTED


def repository(hub, repo):
    if repo not in ['rollingfruit/'+name for name in SUPPORTED]:
        raise ValueError('仓库尚无候选构建映射')
    return hub._gh_json(['api', 'repos/'+repo])


def branches(hub, repo):
    info = repository(hub, repo)
    pages = hub._gh_json(['api', 'repos/'+repo+'/branches?per_page=100', '--paginate', '--slurp'])
    return {'repo': repo, 'default_branch': info['default_branch'],
            'branches': [{'name': b['name'], 'sha': b['commit']['sha']} for page in pages for b in page]}


def resolve(hub, members):
    from pr_pipeline_hub import utc_now, redact
    from review_policy import select
    if not isinstance(members, list) or not 1 <= len(members) <= len(SUPPORTED):
        raise ValueError('请选择非空的仓库分支组合')
    results = []
    seen = set()
    for member in members:
        try:
            repo = member['repo']
            if repo in seen: raise ValueError('同仓最多选择一个分支')
            seen.add(repo)
            info = repository(hub, repo)
            head_ref = member['head_ref']
            base_ref = member.get('base_ref') or info['default_branch']
            def ref(name):
                if not isinstance(name,str) or not name or len(name)>255 or any(ord(c)<32 for c in name):
                    raise ValueError('Invalid branch name')
                return hub._gh_json(['api',f'repos/{repo}/git/ref/heads/{quote(name,safe="")}'])['object']['sha']
            head, base = ref(head_ref), ref(base_ref)
            # Local tree diff during execution remains authoritative for build-risk approval.
            comparison = hub._gh_json(['api',f'repos/{repo}/compare/{base}...{head}'])
            files = sorted({n for f in comparison.get('files',[]) for n in (f['filename'],f.get('previous_filename')) if n})
            risks = select(repo,files)['risky_files']
            if len(comparison.get('files',[])) >= 300: risks = sorted(set(risks+['compare-file-limit: local diff required']))
            results.append({'ok':True,'member':{'repo':repo,'repo_id':info['id'],'pr_number':None,'pr_url':None,
                'title':head_ref,'head_ref':head_ref,'base_ref':base_ref,'head_sha':head,'base_sha':base,
                'checked_at':utc_now(),'changed_files':files,'risky_files':risks}})
        except Exception as error:
            results.append({'ok':False,'error':redact(str(error))[:400]})
    return results
