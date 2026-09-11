"""Prepare separate local/server configs and deploy archive code over existing SSH."""
import io
import json
import os
import secrets
import subprocess
import tarfile
from pathlib import Path

root = Path(__file__).resolve().parent
state = Path('/root/.local/share/newlink-pr-e2e/pipeline')
ssh = '/mnt/c/Windows/System32/OpenSSH/ssh.exe'
host = 'root@119.8.233.58'
config_path = root / '.runtime' / 'pipeline-server.json'
config = json.loads(config_path.read_text()) if config_path.exists() else {'view_token': secrets.token_urlsafe(32)}
config.update({'role': 'read-only-share', 'public_base_url': 'http://119.8.233.58:8080',
               'local_base_url': 'http://127.0.0.1', 'local_api_url': 'http://127.0.0.1:8788',
               'ssh_host': host, 'ssh_executable': ssh, 'data_dir': str(state),
               'first_run': '20260908-203211-6bb7f6', 'poll_seconds': 10})
config_path.write_text(json.dumps(config, indent=2))
os.chmod(config_path, 0o600)
local = {'role': 'local-execution', 'base_url': 'http://127.0.0.1',
         'api_url': 'http://127.0.0.1:8788', 'public_base_url': config['public_base_url'],
         'allowed_repos': 'rollingfruit/agent-governance-gw,rollingfruit/multica-aiwelink'}
(root / '.runtime' / 'pipeline-local.json').write_text(json.dumps(local, indent=2))
agent_path = root / '.runtime' / 'pipeline-agent.json'
agent = json.loads(agent_path.read_text(encoding='utf-8-sig'))
agent['base_url'] = local['base_url']
agent['public_base_url'] = config['public_base_url']
agent['allow_local_web_url'] = False
agent_path.write_text(json.dumps(agent, indent=2))
files = [root / name for name in ['share_viewer.py', 'pr_pipeline_hub.py', 'e2e_catalog.py', 'deploy/install-share.py']]
files += list((root / 'static').glob('*'))
data = io.BytesIO()
with tarfile.open(fileobj=data, mode='w:gz') as tar:
    for path in files:
        tar.add(path, arcname=path.relative_to(root).as_posix())
    payload = json.dumps({'view_token': config['view_token'], 'public_base_url': config['public_base_url']}).encode()
    info = tarfile.TarInfo('provision.json')
    info.mode = 0o600
    info.size = len(payload)
    tar.addfile(info, io.BytesIO(payload))
subprocess.run([ssh, '-o', 'BatchMode=yes', host, 'mkdir -p /opt/pr-e2e-share'], check=True)
subprocess.run([ssh, '-o', 'BatchMode=yes', host, 'tar -xzf - -C /opt/pr-e2e-share'], input=data.getvalue(), check=True)
subprocess.run([ssh, '-o', 'BatchMode=yes', host, '/usr/local/bin/python3.11 /opt/pr-e2e-share/deploy/install-share.py'], check=True)
certificate = subprocess.run([ssh, '-o', 'BatchMode=yes', host, 'cat /etc/pr-e2e-share/server.crt'], capture_output=True, check=True)
(root / '.runtime/ecs-share.crt').write_bytes(certificate.stdout)
print('Server deployed. Local and server configs prepared; no credentials printed.')
