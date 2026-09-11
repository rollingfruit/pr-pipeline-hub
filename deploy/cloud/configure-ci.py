"""Prepare a fresh CI profile without switching the existing queue consumer."""
import json
import os
from pathlib import Path
import pwd
import secrets
import shlex
import shutil

root=Path('/opt/pr-pipeline-ci')
home=Path('/var/lib/pr-e2e')
account=pwd.getpwnam('pr-e2e')
directory=Path('/etc/pr-e2e/secrets')
directory.mkdir(mode=0o750,parents=True,exist_ok=True)
os.chown(directory,0,account.pw_gid)

def secret(name,value):
    p=directory/name
    if not p.exists():
        fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o640)
        with os.fdopen(fd,'w') as target:target.write(value+'\n')
        os.chown(p,0,account.pw_gid)

env={}
for line in Path('/etc/pr-pipeline-control.env').read_text().splitlines():
    if not line.strip() or line.lstrip().startswith('#'):continue
    key,sep,value=line.partition('=')
    if sep:env[key]=shlex.split(value)[0] if value else ''
for key,name in [('PIPELINE_WORKER_TOKEN','worker-token'),('PIPELINE_DATABASE_URL','database-url')]:
    if not env.get(key):raise ValueError('Existing control credential missing: '+key)
    secret(name,env[key])
secret('submit-password',secrets.token_urlsafe(32))
github=json.loads(Path('/opt/swr-push-helper/config.json').read_text()).get('github_token','')
if github:secret('github-token',github)
for name in ('state','data','workspace','state/agent-workspace','state/docker-config','state/docker-config/cli-plugins'):
    p=home/name;p.mkdir(parents=True,exist_ok=True);os.chown(p,account.pw_uid,account.pw_gid)
shutil.copy2('/opt/pr-pipeline-tools/docker-compose',home/'state/docker-config/cli-plugins/docker-compose')
(home/'state/docker-config/cli-plugins/docker-compose').chmod(0o755)
shutil.copy2('/usr/local/lib/docker/cli-plugins/docker-buildx',home/'state/docker-config/cli-plugins/docker-buildx')
(home/'state/docker-config/cli-plugins/docker-buildx').chmod(0o755)
settings=home/'state/settings.json'
if not settings.exists():
    values=json.loads((root/'deploy/cloud/runtime.example.json').read_text())
    values.update(CODEX_HOME=str(home/'codex-home'),TEST_WORKSPACE=str(home/'state/agent-workspace'),
                  TEST_ADMIN_PASSWORD=secrets.token_urlsafe(24),CODEX_MODEL='gpt-5.6-sol')
    settings.write_text(json.dumps(values,indent=2));settings.chmod(0o600);os.chown(settings,account.pw_uid,account.pw_gid)
config=Path('/etc/pr-e2e/config.toml')
if config.exists():raise ValueError('CI profile exists; review changes instead of overwriting')
text=(root/'deploy/cloud/config.example.toml').read_text()
text=text.replace('allow_private_http = false','allow_private_http = true\nworker_port = 8794\ndocker_host = "unix:///run/pr-e2e/docker.sock"\nworker_id = "ecs-liusong-ci-e2e"')
text=text.replace('https://pipeline.example.com','http://119.8.233.58:8080')
text=text.replace('/var/lib/pr-pipeline/workspace',str(home/'workspace')).replace('/var/lib/pr-pipeline/e2e',str(home/'state'))
text=text.replace('/var/lib/pr-pipeline/data',str(home/'data')).replace('/var/lib/pr-pipeline/archives','/var/lib/pr-e2e-share')
text=text.replace('/opt/pr-pipeline/stack',str(root/'stack')).replace('/etc/pr-pipeline/secrets','/etc/pr-e2e/secrets')
text=text.replace('docker_bridge = "172.17.0.1"','docker_bridge = "172.30.250.1"')
if github:text=text.replace('# github_token =','github_token =')
config.write_text(text);config.chmod(0o640);os.chown(config,0,account.pw_gid)
print('CI profile prepared. Secrets not printed. Worker not started. Github credential present:',bool(github))
