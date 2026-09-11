"""Local authenticated control client over the existing Windows SSH identity."""
import json
import os
import subprocess
from pathlib import Path


def rpc(path, body=None):
    base=os.environ.get('PIPELINE_CONTROL_URL')
    if base:
        import urllib.request
        import urllib.error
        data=json.dumps(body).encode() if body is not None else None
        request=urllib.request.Request(base.rstrip('/')+path,data,{
            'Content-Type':'application/json','X-Worker-Token':os.environ['PIPELINE_WORKER_TOKEN']})
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            from pr_pipeline_hub import redact
            raise RuntimeError('Control HTTP '+str(e.code)+': '+redact(e.read().decode(errors='replace'))[:500]) from e
    sockets = sorted(Path('/run/WSL').glob('*_interop'), key=lambda p:p.stat().st_mtime)
    env = os.environ.copy()
    if sockets:
        env['WSL_INTEROP'] = str(sockets[-1])
    payload = {'path':path}
    if body is not None:
        payload['body'] = body
    result = subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe', '-o', 'BatchMode=yes',
        '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2', 'root@119.8.233.58',
        '/usr/local/bin/python3.11 /opt/pr-e2e-share/control_rpc.py'],
        input=json.dumps(payload), text=True, capture_output=True, env=env, timeout=20 if path.endswith('/progress') else 45)
    if result.returncode:
        from pr_pipeline_hub import redact
        raise RuntimeError('ECS control request failed: '+redact(result.stdout or result.stderr)[:500])
    return json.loads(result.stdout)
