"""Start verified baseline images for infrastructure diagnosis, not PR acceptance."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0,'/opt/pr-pipeline-ci')
from cloud_config import load,activate
cfg=load('/etc/pr-e2e/config.toml','worker',True)
activate(cfg,'worker')
sys.path.insert(0,cfg['paths']['stack'])
import stack

parser=argparse.ArgumentParser()
parser.add_argument('--from-batch',required=True)
parser.add_argument('--suite',choices=['E01','E02','E03'])
parser.add_argument('--adapter-fix',action='store_true')
args=parser.parse_args()
if not re.fullmatch(r'[a-zA-Z0-9-]+',args.from_batch):raise ValueError('Invalid batch ID')
batch=json.loads((Path(cfg['paths']['data'])/'runs'/args.from_batch/'run.json').read_text())
private=stack.STATE/'local-stack'
private.mkdir(exist_ok=True)
with (stack.STATE/'environment.lock').open('a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    from resource_gate import inspect
    resource=inspect()
    if not args.suite and resource.get('enabled') and not resource['ready']:
        raise RuntimeError('Waiting for resources: '+json.dumps(resource))
    images={};records={}
    adapter=None
    if args.adapter_fix:
        adapter=json.loads((stack.STATE/'adapter-fixes/mattermost-idempotency.json').read_text())
        if adapter['scope']!='unmerged-test-adapter-fix' or adapter['base_sha']!=batch['baseline_revisions']['mattermost']:
            raise ValueError('Adapter fix does not match this diagnostic baseline')
    for service,(name,variable,_) in stack.SERVICES.items():
        member=next((m for m in batch['members'] if m['repo'].endswith('/'+name)),None)
        sha=member['base_sha'] if member else batch['baseline_revisions'][name]
        if name=='mattermost' and adapter:sha=adapter['source_sha']
        record=json.loads((stack.STATE/'build-contexts'/f'{name}-{sha[:12]}'/'build.json').read_text())
        actual=stack.capture(['docker','image','inspect','--format','{{.Id}}',record['image']])
        if record['source_sha']!=sha or record['exit_code']!=0 or record.get('image_id')!=actual:
            raise ValueError('Unverified diagnostic image: '+service)
        images[variable]=actual;records[service]=record
    env=stack.runtime_environment(private,images)
    env['COMPOSE_PROJECT_NAME']='newlink-e2e-local'
    stack.output_json(private/'diagnostic-images.json',{'scope':'baseline-environment-diagnostic',
        'pr_acceptance':False,'from_batch':args.from_batch,'adapter_fix':adapter,'images':records})
    if args.suite:
        subprocess.run([sys.executable,str(stack.HERE/'bootstrap.py')],env=env,stdin=subprocess.DEVNULL,check=True)
        result=subprocess.run([sys.executable,str(stack.HERE/'diagnose-suite.py'),args.suite],env=env,stdin=subprocess.DEVNULL)
        raise SystemExit(result.returncode)
    subprocess.run(['docker','compose','-f',str(stack.HERE/'compose.yaml'),'up','-d','--wait','--wait-timeout','300'],
                   env=env,stdin=subprocess.DEVNULL,check=True)
    subprocess.run([sys.executable,str(stack.HERE/'bootstrap.py')],env=env,stdin=subprocess.DEVNULL,check=True)
    subprocess.run([sys.executable,str(stack.HERE/'bootstrap.py'),'--check'],env=env,stdin=subprocess.DEVNULL,check=True)
    print(json.dumps({'scope':'baseline-environment-diagnostic','ready':True,'pr_acceptance':False}))
