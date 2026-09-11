"""Local authenticated control client over the existing Windows SSH identity."""
import json
import os
import subprocess
from pathlib import Path


def rpc(path, body=None):
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
        raise RuntimeError('ECS control request failed: '+result.stdout[:500])
    return json.loads(result.stdout)
