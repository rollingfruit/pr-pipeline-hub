"""Install control plane separately; switch nginx only after readiness succeeds."""
import json
import os
import secrets
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path('/opt/pr-e2e-share')


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


env = Path('/etc/pr-pipeline-control.env')
if not env.exists():
    existing = dict(line.split('=', 1) for line in Path('/etc/pr-e2e-share.env').read_text().splitlines() if '=' in line)
    password = secrets.token_urlsafe(36)
    existing.update(PIPELINE_DATABASE_URL=f'postgresql://prpipeline:{password}@127.0.0.1:5439/prpipeline',
                    PIPELINE_WORKER_TOKEN=secrets.token_urlsafe(36), PIPELINE_WEBHOOK_SECRET=secrets.token_urlsafe(36))
    env.write_text(''.join(f'{key}={value}\n' for key, value in existing.items()))
    env.chmod(0o600)
    db_env = Path('/etc/pr-pipeline-postgres.env')
    db_env.write_text(f'POSTGRES_USER=prpipeline\nPOSTGRES_DB=prpipeline\nPOSTGRES_PASSWORD={password}\n')
    db_env.chmod(0o600)

# Explicit deployment policy: public read-only dashboard, never public Worker access.
settings = dict(line.split('=', 1) for line in env.read_text().splitlines() if '=' in line)
settings.update(PIPELINE_PUBLIC_READ='true', PIPELINE_EMBED_VIEW_TOKEN='false')
env.write_text(''.join(f'{key}={value}\n' for key, value in settings.items()))
env.chmod(0o600)

exists = subprocess.run(['docker', 'inspect', 'pr-pipeline-postgres'], capture_output=True).returncode == 0
if not exists:
    run('docker', 'run', '-d', '--name', 'pr-pipeline-postgres', '--restart', 'unless-stopped',
        '--env-file', '/etc/pr-pipeline-postgres.env', '-p', '127.0.0.1:5439:5432',
        '-v', 'pr-pipeline-postgres:/var/lib/postgresql/data', 'postgres:16.9')
else:
    run('docker', 'start', 'pr-pipeline-postgres')
for attempt in range(30):
    if subprocess.run(['docker', 'exec', 'pr-pipeline-postgres', 'pg_isready', '-U', 'prpipeline'], capture_output=True).returncode == 0:
        break
    time.sleep(2)
else:
    raise RuntimeError('PostgreSQL is not ready; existing viewer unchanged')

venv = ROOT / '.control-venv'
if not venv.exists():
    run('/usr/local/bin/python3.11', '-m', 'venv', str(venv))
run(str(venv / 'bin/pip'), 'install', '-r', str(ROOT / 'control_requirements.txt'))
Path('/etc/systemd/system/pr-pipeline-control.service').write_text('''[Unit]
Description=PR Pipeline control plane (observation mode)
After=network.target docker.service
[Service]
User=prpipeline
Group=prpipeline
WorkingDirectory=/opt/pr-e2e-share
EnvironmentFile=/etc/pr-pipeline-control.env
ExecStart=/opt/pr-e2e-share/.control-venv/bin/uvicorn control_api:create_app --factory --host 127.0.0.1 --port 8792 --no-access-log
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
[Install]
WantedBy=multi-user.target
''')
run('systemctl', 'daemon-reload')
run('systemctl', 'enable', '--now', 'pr-pipeline-control')
run('systemctl', 'restart', 'pr-pipeline-control')
for attempt in range(30):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8792/api/health', timeout=2) as response:
            if json.load(response)['status'] == 'ok':
                break
    except Exception:
        time.sleep(2)
else:
    raise RuntimeError('Control plane not ready; existing viewer unchanged')
nginx = Path('/etc/nginx/conf.d/pr-e2e-share.conf')
backup = nginx.with_suffix('.pre-control')
if not backup.exists():
    backup.write_bytes(nginx.read_bytes())
text = nginx.read_text().replace('proxy_pass http://127.0.0.1:8791;', 'proxy_pass http://127.0.0.1:8792;')
if 'location /internal/' not in text:
    text = text.replace('    location / {', '    client_max_body_size 2m;\n    location /internal/ { return 404; }\n    location / {')
nginx.write_text(text)
try:
    run('nginx', '-t')
except Exception:
    nginx.write_bytes(backup.read_bytes())
    raise
run('nginx', '-s', 'reload')
print('Control plane ready; private PostgreSQL, existing archives and repository hook settings preserved.')
