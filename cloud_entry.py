"""Linux/cloud service entrypoints driven by one non-secret TOML profile."""
import argparse
import json
import os
import runpy
import sys
import threading
import time
from pathlib import Path
from cloud_config import load,activate,enabled


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('role',choices=['control','editor','worker','publisher','monitor','register','model','check'])
    parser.add_argument('--check-files',action='store_true')
    args=parser.parse_args()
    role=args.role
    cfg=load(args.config,role,check_files=role!='check' or args.check_files)
    if role=='check':
        print(json.dumps({'config_valid':True,'features':cfg['features'],'runtime_verified':False}));return
    activate(cfg,'worker' if role in {'monitor','register'} else role)
    if role=='control':
        import uvicorn
        uvicorn.run('control_api:create_app',factory=True,host=cfg.get('control_bind','127.0.0.1'),port=8792);return
    if role=='model':
        sys.path.insert(0,cfg['paths']['stack'])
        from stack import config
        if not config().get('CODEX_MODEL'):
            raise ValueError('Set CODEX_MODEL to a model available to the server Codex login before starting the model adapter')
        sys.argv=['codex_model_bridge.py','--configure','--docker-bind',cfg.get('docker_bridge','172.17.0.1')]
        runpy.run_path(str(Path(cfg['paths']['stack'])/'codex_model_bridge.py'),run_name='__main__');return
    if role=='publisher':
        from publish_results import publish,fingerprint
        from pr_pipeline_hub import atomic_json,redact,utc_now
        data=Path(cfg['paths']['data']);cache={}
        worker_url='http://127.0.0.1:'+os.environ['PIPELINE_WORKER_PORT']
        publish_cfg={'data_dir':str(data),'local_api_url':worker_url,'local_base_url':worker_url,
                     'public_base_url':cfg['urls']['public'],'control_url':cfg['urls']['control']}
        while True:
            for root in (data/'runs').glob('*'):
                if not (root/'run.json').is_file():continue
                try:
                    stamp=fingerprint(root)
                    if cache.get(root.name)==stamp:continue
                    publish(publish_cfg,root.name);cache[root.name]=stamp
                except Exception as error:
                    atomic_json(root/'publication.json',{'status':'error','at':utc_now(),'error':redact(str(error))[:1000]})
            time.sleep(10)
    os.environ['PIPELINE_NO_WORKER']='0' if role=='worker' else '1'
    os.environ['PIPELINE_ALLOWED_REPOS']=','.join(cfg['repositories'])
    os.environ['PIPELINE_TRIGGER_TOKEN']=os.environ['PIPELINE_WORKER_TOKEN']
    from pr_pipeline_hub import PipelineHub,PipelineHTTPServer
    hub=PipelineHub(Path(cfg['paths']['data']) if role=='worker' else Path(cfg['paths']['state'])/role,cfg['urls']['public'])
    if role=='worker':
        from control_worker import work
        threading.Thread(target=work,args=(hub,),daemon=True,name='control-queue-worker').start()
        PipelineHTTPServer(('127.0.0.1',int(os.environ['PIPELINE_WORKER_PORT'])),hub).serve_forever()
    elif role=='editor':
        from local_selection import Handler,ThreadingHTTPServer
        server=ThreadingHTTPServer((os.environ['PIPELINE_EDITOR_BIND'],8793),Handler)
        server.hub=hub;server.serve_forever()
    elif role=='register':
        from control_client import rpc
        for repo in cfg['repositories']:
            metadata=hub._gh_json(['api','repos/'+repo])
            rpc('/internal/repositories',{'id':metadata['id'],'name':metadata['full_name']})
            print('registered',metadata['full_name'])
    elif role=='monitor':
        if not enabled('monitor'):print('Optional PR discovery disabled');return
        from pr_monitor import Monitor
        monitors=[Monitor(hub._gh_json,path=Path(cfg['paths']['state'])/'monitors'/(r.split('/')[-1]+'.json'),repo=r) for r in cfg['repositories']]
        while True:
            for monitor in monitors:
                try:monitor.tick()
                except Exception as error:print(type(error).__name__,flush=True)
            time.sleep(60)


if __name__=='__main__':main()
