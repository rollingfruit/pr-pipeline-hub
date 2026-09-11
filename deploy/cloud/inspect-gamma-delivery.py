"""Read-only message correlation for a dedicated test account; never prints auth."""
import json
from pathlib import Path
import sys
import urllib.request
sys.path.insert(0,'/opt/pr-pipeline-ci')
from gamma_access import GammaAccess
root=Path('/var/lib/pr-e2e/gamma-diagnostics/gamma-check-20260911-172804-191bdf/private')
cfg=json.loads((root/'settings.json').read_text())
access=GammaAccess('a5932430eb2f')
try:
    access.connect()
    service=next(s for s in access.resource('services')['items'] if s['spec'].get('selector',{}).get('app')=='service-router')
    base=access.forward(service['spec']['clusterIP'],80,0)
    req=urllib.request.Request(base+'/api/v4/users/login',data=json.dumps({'login_id':cfg['TEST_ADMIN_USER'],'password':cfg['TEST_ADMIN_PASSWORD']}).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req) as response:
        token=response.headers['Token']
    req=urllib.request.Request(base+'/api/v4/channels/xdje87yk9prkzyapo6is1aiate/posts',headers={'Authorization':'Bearer '+token})
    with urllib.request.urlopen(req) as response:
        data=json.load(response)
    for post in data.get('posts',{}).values():
        props=post.get('props',{})
        print(json.dumps({'id':post['id'],'user':post['user_id'],'message':post['message'][:180],
            'props':{k:v for k,v in props.items() if k in ('source_post_id','agent_run_id','agent_run_companion_kind','agent_task_id','agent_reply_type','trace_id')}}))
    service=next(s for s in access.resource('services')['items'] if s['spec'].get('selector',{}).get('app')=='multica-server')
    base=access.forward(service['spec']['clusterIP'],8080,0)
    internal=json.loads((root/'internal.json').read_text())['token']
    req=urllib.request.Request(base+'/v1/agent/im-integrations/agent-runs/3985b0c0-7be6-4a0e-a981-56c7c1709d3e',headers={'X-Auth-Token':internal})
    with urllib.request.urlopen(req) as response: run=json.load(response)
    print(json.dumps({k:run.get(k) for k in ('id','status','failure','error','anchor_post_id','final_response','source_available')}))
finally: access.close()
