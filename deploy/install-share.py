"""Install an independent HTTPS archive viewer; leave port 80 and legacy Hub alone."""
import json
import os
import subprocess
from pathlib import Path


def run(*args):
    subprocess.run(args, check=True)


root = Path('/opt/pr-e2e-share')
settings = json.loads((root / 'provision.json').read_text())
cert = Path('/etc/pr-e2e-share')
cert.mkdir(mode=0o750, exist_ok=True)
if not (cert / 'server.crt').exists():
    run('openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-days', '365',
        '-keyout', str(cert / 'server.key'), '-out', str(cert / 'server.crt'),
        '-subj', '/CN=119.8.233.58', '-addext', 'subjectAltName=IP:119.8.233.58')
os.chmod(cert / 'server.key', 0o600)
env = Path('/etc/pr-e2e-share.env')
env.write_text('PIPELINE_PUBLIC_BASE_URL=' + settings['public_base_url'] + '\nPIPELINE_VIEW_TOKEN=' + settings['view_token'] + '\n')
os.chmod(env, 0o600)
(root / 'provision.json').unlink()
data = Path('/var/lib/pr-e2e-share')
data.mkdir(mode=0o755, exist_ok=True)
(data / 'runs').mkdir(exist_ok=True)
Path('/etc/systemd/system/pr-e2e-share.service').write_text('''[Unit]
Description=Read-only local E2E results archive
After=network.target
[Service]
User=prpipeline
Group=prpipeline
WorkingDirectory=/opt/pr-e2e-share
EnvironmentFile=/etc/pr-e2e-share.env
ExecStart=/usr/local/bin/python3.11 /opt/pr-e2e-share/share_viewer.py serve
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
[Install]
WantedBy=multi-user.target
''')
Path('/etc/nginx/conf.d/pr-e2e-share.conf').write_text('''server {
    listen 8080;
    server_name 119.8.233.58;
    access_log off;
    location / {
        proxy_pass http://127.0.0.1:8791;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto http;
        proxy_read_timeout 120s;
    }
}
server {
    listen 443 ssl;
    server_name 119.8.233.58;
    ssl_certificate /etc/pr-e2e-share/server.crt;
    ssl_certificate_key /etc/pr-e2e-share/server.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    access_log off;
    location / {
        proxy_pass http://127.0.0.1:8791;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 120s;
    }
}
''')
run('nginx', '-t')
run('systemctl', 'daemon-reload')
run('systemctl', 'enable', '--now', 'pr-e2e-share')
run('systemctl', 'restart', 'pr-e2e-share')
run('nginx', '-s', 'reload')
