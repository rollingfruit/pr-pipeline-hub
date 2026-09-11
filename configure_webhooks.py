"""Enable only this Hub's repository hooks; never enumerate or backfill PRs."""
import json
import os
import subprocess
from pathlib import Path
from control_client import rpc
from pr_pipeline_hub import PipelineHub, atomic_json, utc_now
from review_policy import REPOSITORIES

ROOT = Path(__file__).resolve().parent
URL = 'http://119.8.233.58:8080/webhooks/github'


def main():
    os.environ['PIPELINE_NO_WORKER'] = '1'
    hub = PipelineHub(ROOT / '.runtime/registry-tool')
    # Secret crosses the established encrypted SSH session only; no argv/log exposure.
    secret_result = subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes',
        'root@119.8.233.58', "sed -n 's/^PIPELINE_WEBHOOK_SECRET=//p' /etc/pr-pipeline-control.env"],
        capture_output=True,text=True,check=True,timeout=30)
    secret = secret_result.stdout.strip()
    if len(secret)<32:
        raise RuntimeError('Webhook secret unavailable')
    records = []
    for name in REPOSITORIES:
        repo = hub._gh_json(['api','repos/rollingfruit/'+name])
        if not repo.get('permissions',{}).get('admin'):
            raise RuntimeError('Missing repository admin: '+name)
        canonical = repo['full_name']
        rpc('/internal/repositories',{'id':repo['id'],'name':canonical})
        hooks = hub._gh_json(['api',f'repos/{canonical}/hooks','--paginate','--slurp'])
        ours = [h for page in hooks for h in page if h.get('config',{}).get('url')==URL]
        if len(ours)>1:
            raise RuntimeError('Multiple matching hooks require reconciliation: '+canonical)
        endpoint = f"repos/{canonical}/hooks" + (f"/{ours[0]['id']}" if ours else '')
        payload = {'name':'web','active':True,'events':['pull_request','push'],
            'config':{'url':URL,'content_type':'json','secret':secret,'insecure_ssl':'0'}}
        result = subprocess.run([hub.gh_cli,'api',endpoint,'--method','PATCH' if ours else 'POST','--input','-'],
            input=json.dumps(payload),text=True,capture_output=True,timeout=60)
        if result.returncode:
            raise RuntimeError('Webhook configuration failed: '+canonical+'; HTTP details withheld')
        hook = json.loads(result.stdout)
        verified = hub._gh_json(['api',f"repos/{canonical}/hooks/{hook['id']}"])
        if not verified['active'] or verified['config']['url']!=URL:
            raise RuntimeError('Webhook verification failed: '+canonical)
        record = {'repo':canonical,'repository_id':repo['id'],'hook_id':hook['id'],
                  'active':verified['active'],'events':verified['events'],'configured_at':utc_now()}
        records.append(record)
        atomic_json(ROOT / '.runtime/webhooks.json',records)
        print(json.dumps(record),flush=True)
    print('12 hooks enabled. No historical PRs scanned or merged.')


if __name__=='__main__':
    main()
