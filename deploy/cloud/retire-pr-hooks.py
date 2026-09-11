"""Disable only this host's Pipeline GitHub hooks; never enumerate PRs."""
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit
sys.path.insert(0,'/opt/pr-pipeline-ci')
from cloud_config import activate,load
cfg=load('/etc/pr-e2e/config.toml','worker');activate(cfg,'worker')
results=[]
for repo in cfg['repositories']:
    command=['/usr/local/bin/gh','api','repos/'+repo+'/hooks']
    response=subprocess.run(command,capture_output=True,text=True)
    if response.returncode:
        results.append({'repo':repo,'state':'permission_or_network_error'});continue
    owned=[]
    for hook in json.loads(response.stdout):
        url=urlsplit(hook.get('config',{}).get('url',''))
        if url.hostname=='119.8.233.58' and url.path in {'/webhooks/github','/pipeline/webhooks/github'}:
            owned.append(hook['id'])
            if hook.get('active'):
                update=subprocess.run(command[:-1]+[command[-1]+'/'+str(hook['id']),'-X','PATCH','-F','active=false'],capture_output=True,text=True)
                if update.returncode:raise SystemExit('Could not disable owned hook for '+repo)
    results.append({'repo':repo,'owned_hooks_disabled':owned})
Path('/var/lib/pr-e2e/state/retired-pr-hooks.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results))
