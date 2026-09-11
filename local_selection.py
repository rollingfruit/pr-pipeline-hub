"""Loopback-only authenticated PR selection. All execution uses the ECS queue."""
import argparse
import base64
import json
import os
import secrets
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(32)


class Handler(BaseHTTPRequestHandler):
    def cloud_authorized(self):
        if os.environ.get('PIPELINE_AUTH_MODE')=='robot-session':
            from robot_session import username
            self.actor=username(self.headers.get('Cookie',''))
            return bool(self.actor)
        if os.environ.get('PIPELINE_CLOUD_PROFILE')!='1':return True
        expected=base64.b64encode((os.environ.get('PIPELINE_SUBMIT_USER','operator')+':'+os.environ.get('PIPELINE_SUBMIT_PASSWORD','')).encode()).decode()
        return bool(os.environ.get('PIPELINE_SUBMIT_PASSWORD')) and secrets.compare_digest(self.headers.get('Authorization',''),'Basic '+expected)

    def allowed(self):
        if os.environ.get('PIPELINE_CLOUD_PROFILE')=='1':
            return self.headers.get('Host')==urlsplit(os.environ['PIPELINE_EDITOR_URL']).netloc
        return self.headers.get('Host') in {'127.0.0.1:8793', 'localhost:8793'}

    def respond(self, status, body, content='application/json'):
        data = (json.dumps(body, ensure_ascii=False) if content == 'application/json' else body).encode()
        self.send_response(status)
        self.send_header('Content-Type', content + '; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'")
        self.send_header('Content-Length', str(len(data)))
        if status==401 and os.environ.get('PIPELINE_AUTH_MODE')!='robot-session':self.send_header('WWW-Authenticate','Basic realm="Pipeline submission", charset="UTF-8"')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/internal/session':
            if self.client_address[0] not in {'127.0.0.1', '::1'}:
                return self.respond(404, {})
            from robot_session import check, Unavailable
            try:
                user = check(self.headers.get('Cookie', ''))
                return self.respond(200 if user else 401, {'user': user or None})
            except Unavailable:
                return self.respond(503, {'error': 'Robot CI authentication unavailable'})
        if not self.cloud_authorized():return self.respond(401,{'error':'Submitter login required'})
        if not self.allowed():
            return self.respond(403, {'error': 'Loopback host required'})
        if self.path=='/api/catalog':
            from e2e_catalog import CATALOG
            from batches import SUPPORTED
            from control_client import rpc
            from cloud_config import enabled
            return self.respond(200,{'suites':CATALOG,'supported':SUPPORTED,'monitors':[],
                'features':{key:enabled(key) for key in ('code_review','github_write')}})
        if self.path.startswith('/api/branches?'):
            from urllib.parse import parse_qs
            from branch_batches import branches
            try:return self.respond(200,branches(self.server.hub,parse_qs(urlsplit(self.path).query)['repo'][0]))
            except Exception as error:
                from pr_pipeline_hub import redact
                return self.respond(409,{'error':redact(str(error))[:400]})
        if self.path == '/api/prs':
            from pr_monitor import STATE, REPO
            state = json.loads(STATE.read_text())
            prs = sorted((p for p in state['seen'].values() if p['state'] == 'open'), key=lambda p: p['number'], reverse=True)
            return self.respond(200, {'repo': REPO, 'checked_at': state.get('checked_at'), 'prs': prs})
        if self.path != '/':
            return self.respond(404, {})
        page=(ROOT/'static/branch-editor.html').read_text(encoding='utf-8').replace('__TOKEN__', TOKEN)
        page=page.replace('__PIPELINE_BASE__',os.environ.get('PIPELINE_PUBLIC_BASE_URL','').rstrip('/'))
        page=page.replace('__EDITOR_API_BASE__','/submit' if os.environ.get('PIPELINE_CLOUD_PROFILE')=='1' else '')
        page=page.replace('http://119.8.233.58:8080/batches',os.environ.get('PIPELINE_PUBLIC_BASE_URL','http://119.8.233.58:8080').rstrip('/')+'/batches')
        return self.respond(200,page,'text/html')

    def do_POST(self):
        if not self.cloud_authorized():return self.respond(401,{'error':'Submitter login required'})
        if not self.allowed() or not secrets.compare_digest(self.headers.get('X-Selection-Token', ''), TOKEN):
            return self.respond(403, {'error': 'Local selection token required'})
        origin = self.headers.get('Origin')
        origins={'http://127.0.0.1:8793', 'http://localhost:8793'}
        if os.environ.get('PIPELINE_CLOUD_PROFILE')=='1':
            url=urlsplit(os.environ['PIPELINE_EDITOR_URL']);origins={url.scheme+'://'+url.netloc}
        if origin and origin not in origins:
            return self.respond(403, {'error': 'Invalid origin'})
        try:
            if self.path in {'/api/batches/resolve','/api/branches/resolve','/api/batches'}:
                length=int(self.headers.get('Content-Length',0))
                if not 0<length<=65536:return self.respond(413,{})
                body=json.loads(self.rfile.read(length))
                from batches import resolve,submit
                if self.path=='/api/branches/resolve':
                    from branch_batches import resolve as branch_resolve
                    return self.respond(200,{'results':branch_resolve(self.server.hub,body['members'])})
                if self.path.endswith('/resolve'):
                    return self.respond(200,{'results':resolve(self.server.hub,body['urls'])})
                if body.get('source_mode')!='branch':return self.respond(409,{'error':'请使用分支组合提交；PR 自动验证已关闭'})
                body['requested_by']=getattr(self,'actor','local-selection')
                result=submit(self.server.hub,body)
                result['web_url']=self.server.hub.public_base_url.rstrip('/')+result['web_path']
                return self.respond(200,result)
            if self.path != '/api/enqueue':
                return self.respond(404, {})
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 4096:
                return self.respond(413, {})
            body = json.loads(self.rfile.read(length))
            return self.respond(409,{'error':'单 PR 入队已停用，请创建联合验证批次'})
            from pr_monitor import REPO, STATE
            number = int(body['number'])
            state = json.loads(STATE.read_text())
            pr = state['seen'].get(str(number))
            if not pr or pr['state'] != 'open':
                raise ValueError('PR not in the current monitored open set')
            from control_worker import submit
            result = submit(self.server.hub, f'https://github.com/{REPO}/pull/{number}', 'local-selection',
                            'browser-e2e', None, False, '', 'merge')
            self.respond(200, result)
        except Exception as error:
            from pr_pipeline_hub import redact
            self.respond(409, {'error': redact(str(error))[:600]})


PAGE = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PR 入队 · Pipeline Hub</title><style>
*{box-sizing:border-box}body{font:14px system-ui;margin:0;color:#202b32;background:#f5f7f8;letter-spacing:0}
header{padding:24px;border-bottom:1px solid #dce2e5;background:white}h1{font-size:22px;margin:0 0 10px}
main{max-width:1080px;margin:auto;padding:24px}article{background:white;border-bottom:1px solid #dce2e5;padding:18px 12px;display:flex;gap:16px;align-items:center}article div{flex:1;min-width:0}a{color:#007d88;overflow-wrap:anywhere}button{background:#087f76;border:0;border-radius:4px;color:white;padding:10px 16px;cursor:pointer;flex-shrink:0}button:disabled{opacity:.5;cursor:default}small{display:block;color:#647078;margin-top:8px}#result{white-space:pre-wrap;overflow-wrap:anywhere;margin-top:20px}@media(max-width:500px){main{padding:12px}article{align-items:start;flex-wrap:wrap}}
</style><header><h1>PR 入队</h1><span>本机 Codex / WSL · ECS 单队列 · 观察模式</span></header><main>
<p id="state">正在读取监听结果...</p><section id="prs"></section><p id="result" role="status"></p></main><script>
const result=document.querySelector('#result');
async function load(){const response=await fetch('/api/prs');if(!response.ok)throw Error('监听结果不可用');const data=await response.json();document.querySelector('#state').textContent=data.repo+' · 最近扫描 '+data.checked_at;
for(const pr of data.prs){const row=document.createElement('article'), info=document.createElement('div'), link=document.createElement('a'),meta=document.createElement('small'),button=document.createElement('button');link.textContent='#'+pr.number+' '+pr.title;link.href=pr.html_url;link.target='_blank';link.rel='noreferrer';meta.textContent=pr.head.sha.slice(0,12)+(pr.draft?' · 草稿':' · E01 / E02 / E03 必跑');info.append(link,meta);button.textContent='入队检视';button.disabled=pr.draft;button.onclick=async()=>{button.disabled=true;result.textContent='正在核实 GitHub 版本并入队...';try{const r=await fetch('/api/enqueue',{method:'POST',headers:{'Content-Type':'application/json','X-Selection-Token':'__TOKEN__'},body:JSON.stringify({number:pr.number})});const out=await r.json();if(!r.ok)throw Error(out.error);result.textContent=(out.duplicate?'该版本已有记录：':'已入队：');const a=document.createElement('a');a.href=out.web_url;a.textContent=out.id;a.target='_blank';result.append(a);}catch(e){result.textContent=e.message;}finally{button.disabled=false;}};row.append(info,button);document.querySelector('#prs').append(row);}}
load().catch(e=>result.textContent=e.message);
</script></html>'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--retry', type=int)
    args = parser.parse_args()
    if args.status:
        from control_client import rpc
        from pr_monitor import STATE
        import urllib.request
        remote = rpc('/api/runs')
        rows = remote.get('runs', []) if isinstance(remote, dict) else remote
        print(json.dumps([{k: r.get(k) for k in ('id', 'status', 'pr_number', 'summary')} for r in rows], ensure_ascii=False))
        local = json.load(urllib.request.urlopen('http://127.0.0.1:8788/api/runs'))
        print('LOCAL', json.dumps([{k:r.get(k) for k in ('id','status','pr_number')} for r in local.get('runs',local) if r.get('status') in ('queued','running')]))
        state = json.loads(STATE.read_text())
        print('OPEN', json.dumps([{k:p.get(k) for k in ('number','title','state','draft')} for p in state['seen'].values() if p['state']=='open'], ensure_ascii=False))
        return
    if args.install:
        Path('/etc/systemd/system/pr-local-selection.service').write_text(f'''[Unit]
Description=Local authenticated PR selection
After=network.target
[Service]
WorkingDirectory={ROOT}
ExecStart=/usr/bin/python3 {ROOT}/local_selection.py
Restart=always
RestartSec=5
UMask=0077
[Install]
WantedBy=multi-user.target
''')
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'enable', '--now', 'pr-local-selection'], check=True)
        return
    os.environ['PIPELINE_NO_WORKER'] = '1'
    from pr_pipeline_hub import PipelineHub
    from pr_monitor import STATE
    from control_client import rpc
    config = json.loads((ROOT / '.runtime/pipeline-server.json').read_text())
    sockets = sorted(Path('/run/WSL').glob('*_interop'), key=lambda p: p.stat().st_mtime)
    if sockets:
        os.environ['WSL_INTEROP'] = str(sockets[-1])
    os.environ.update(PIPELINE_PUBLIC_BASE_URL=config['public_base_url'], PIPELINE_SHARE_TOKEN=config['view_token'],
                      PIPELINE_EMBED_VIEW_TOKEN='true', PIPELINE_ALLOWED_REPOS='rollingfruit/agent-governance-gw')
    hub = PipelineHub(STATE.parent / 'selection', config['public_base_url'])
    if args.retry:
        from control_worker import submit
        from pr_monitor import REPO
        result = submit(hub, f'https://github.com/{REPO}/pull/{args.retry}', 'local-retry',
                        'browser-e2e', None, False, 'retry-'+secrets.token_hex(12), 'merge')
        print(json.dumps({k:result.get(k) for k in ('id','status','duplicate')}))
        return
    server = ThreadingHTTPServer(('127.0.0.1', 8793), Handler)
    server.hub = hub
    server.serve_forever()


if __name__ == '__main__':
    main()
