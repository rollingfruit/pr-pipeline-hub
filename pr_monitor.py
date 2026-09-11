"""Authenticated local GitHub polling with a durable outbox, not a second build queue."""
import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from control_client import rpc
from pr_pipeline_hub import PipelineHub, atomic_json, redact, utc_now

ROOT=Path(__file__).resolve().parent
REPO='rollingfruit/agent-governance-gw'
STATE=Path.home()/'.local/share/newlink-pr-e2e/pr-monitor/governance.json'


def snapshot(pr):
    return {key:pr.get(key) for key in ('number','title','html_url','updated_at','created_at','state','draft','merged','merged_at')} | {
        'head':{key:pr['head'].get(key) for key in ('sha','ref')},
        'base':{key:pr['base'].get(key) for key in ('sha','ref')},
        'user':{'login':pr.get('user',{}).get('login','github')}}


def transition(previous, current, initialized_at, baseline_ready=False):
    if current['state']!='open':
        return 'closed' if previous and previous['state']=='open' else None
    if not previous:
        return 'opened' if current['created_at'] >= initialized_at else 'reopened' if baseline_ready else None
    if previous['state']!='open':
        return 'reopened'
    if previous['head']['sha']!=current['head']['sha']:
        return 'synchronize'
    if previous.get('draft') and not current.get('draft'):
        return 'ready_for_review'
    return None


class Monitor:
    def __init__(self, github, send=rpc, path=STATE):
        self.github,self.send,self.path=github,send,path
        self.state=json.loads(path.read_text()) if path.exists() else {
            'initialized_at':utc_now(),'seen':{},'pending':[],'events_delivered':0}

    def save(self):
        atomic_json(self.path,self.state)

    def tick(self):
        sockets=sorted(Path('/run/WSL').glob('*_interop'),key=lambda p:p.stat().st_mtime)
        if sockets:
            os.environ['WSL_INTEROP']=str(sockets[-1])
        if 'repository' not in self.state:
            meta=self.github(['api','repos/'+REPO])
            self.state['repository']={'id':meta['id'],'full_name':meta['full_name']}
        repo=self.state['repository']
        pages=self.github(['api',f"repos/{repo['full_name']}/pulls?state=all&per_page=100&sort=created&direction=desc",'--paginate','--slurp'])
        current={str(p['number']):snapshot(p) for page in pages for p in page}
        for number,old in self.state['seen'].items():
            if old['state']=='open' and number not in current:
                current[number]=snapshot(self.github(['api',f"repos/{repo['full_name']}/pulls/{number}"]))
        for number,pr in current.items():
            action=transition(self.state['seen'].get(number),pr,self.state['initialized_at'],self.state.get('baseline_ready',False))
            if action:
                event={'repository':repo,'action':action,'pull_request':pr,'sender':pr['user']}
                digest=hashlib.sha256(json.dumps(event,sort_keys=True).encode()).hexdigest()
                self.state['pending'].append({'delivery':'poll-'+digest,'digest':digest,'event':event,'source':'github_poll'})
            self.state['seen'][number]=pr
        self.state['checked_at']=utc_now()
        self.state['baseline_ready']=True
        opened=[p for p in current.values() if p['state']=='open']
        self.state['latest']=max(opened,key=lambda p:p['number']) if opened else None
        # Persist before transport: a lost response must replay the identical delivery.
        self.save()
        while self.state['pending']:
            result=self.send('/internal/submit',self.state['pending'][0])
            self.state['pending'].pop(0)
            self.state['events_delivered']+=1
            self.state['last_receipt']=result
            self.save()
        self.state['status']='watching'
        self.state.pop('error',None)
        self.save()
        self.report()
        return self.status()

    def status(self):
        return {key:self.state.get(key) for key in ('initialized_at','checked_at','latest','status','error','events_delivered','last_receipt')} | {
            'repo':self.state.get('repository',{}).get('full_name',REPO),'interval_seconds':60,'pending_events':len(self.state['pending']),
            'pull_requests':sorted(self.state['seen'].values(),key=lambda p:p['number'],reverse=True),
            'mode':'ecs_queue' if (ROOT/'.runtime/ecs-worker.enabled').exists() else 'ingest_only',
            'execution_status':('ECS 单队列已启用；本机 Codex 检视 + WSL E2E；本阶段不依赖 NewLink'
                if (ROOT/'.runtime/ecs-worker.enabled').exists() else 'Agent 调度与 ECS 队列执行器尚未接通')}

    def report(self):
        self.send('/internal/monitors/governance-local-poll',self.status())


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--install',action='store_true')
    args=parser.parse_args()
    if args.install:
        Path('/etc/systemd/system/pr-github-monitor.service').write_text(f'''[Unit]
Description=Authenticated GitHub PR monitor (local WSL, governance)
After=network.target
[Service]
WorkingDirectory={ROOT}
ExecStart=/usr/bin/python3 {ROOT}/pr_monitor.py
Restart=always
RestartSec=15
KillMode=control-group
UMask=0077
[Install]
WantedBy=multi-user.target
''')
        subprocess.run(['systemctl','daemon-reload'],check=True)
        subprocess.run(['systemctl','enable','--now','pr-github-monitor'],check=True)
        return
    os.environ['PIPELINE_NO_WORKER']='1'
    import fcntl
    STATE.parent.mkdir(parents=True,exist_ok=True)
    lock=STATE.with_suffix('.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
    hub=PipelineHub(STATE.parent/'cli-helper')
    monitor=Monitor(hub._gh_json)
    while True:
        try:
            result=monitor.tick()
            print(json.dumps({'status':result['status'],'latest_pr':(result['latest'] or {}).get('number'),
                'checked_at':result['checked_at'],'events_delivered':result['events_delivered']},ensure_ascii=False),flush=True)
        except Exception as error:
            monitor.state.update(status='degraded',error=redact(str(error))[:600])
            monitor.save()
            try:
                monitor.report()
            except Exception:
                pass
            if args.once:
                raise
            print('Monitor degraded: '+redact(str(error))[:200],flush=True)
        if args.once:
            return
        time.sleep(60)


if __name__=='__main__':
    main()
