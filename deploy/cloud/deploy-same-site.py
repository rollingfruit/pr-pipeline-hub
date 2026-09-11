"""Deploy the staged same-site release after both queues are idle."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
import tomllib
import urllib.request

stage=Path('/var/tmp/pipeline-same-site')
ci=Path('/opt/pr-pipeline-ci')
share=Path('/opt/pr-e2e-share')
robot=Path('/opt/swr-push-helper')
config=Path('/etc/pr-e2e/config.toml')
cfg=tomllib.loads(config.read_text())
sys.path.insert(0,str(ci))
from cloud_config import activate
activate(cfg,'worker')
from control_client import rpc
runs=rpc('/api/runs')['runs']
active=[r['id'] for r in runs if r.get('status') in {'running','queued'}]
if active:raise SystemExit('Queue must be idle: '+','.join(active))
db=sqlite3.connect(robot/'data/robot-ci.db')
for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"):
    columns=[r[1] for r in db.execute('PRAGMA table_info(jobs)')]
    if 'status' in columns:
        count=db.execute("SELECT count(*) FROM jobs WHERE status IN ('running','queued')").fetchone()[0]
        if count:raise SystemExit('Robot CI still has active builds')
stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
backup=Path('/var/backups/pr-e2e')/('same-site-'+stamp)
backup.mkdir(mode=0o700)
db.backup(sqlite3.connect(backup/'robot-ci.db'));db.close()
env=dict(os.environ)
db_url=Path(cfg['secrets']['database_url']).read_text().strip()
env['PGDATABASE']=db_url
with (backup/'control.sql').open('wb') as out:
    from urllib.parse import urlsplit,unquote
    database=urlsplit(db_url)
    env['PGPASSWORD']=unquote(database.password or '')
    subprocess.run(['docker','-H','unix:///var/run/docker.sock','exec','-e','PGPASSWORD','pr-pipeline-postgres','pg_dump','-h','127.0.0.1',
                    '-U',unquote(database.username),'-d',database.path.lstrip('/')],env=env,stdout=out,check=True)
with tarfile.open(backup/'config-and-code.tgz','w:gz') as bundle:
    for path in [config,Path('/etc/pr-pipeline-control.env'),Path('/etc/nginx/conf.d'),
                 Path('/etc/systemd/system/swr-push-helper.service.d'),
                 Path('/etc/systemd/system/pr-pipeline-control.service.d')]:
        bundle.add(path,arcname=str(path).lstrip('/'))
    for rel in (stage/'files.json').read_text().splitlines():
        category,name=json.loads(rel)
        roots=[robot] if category=='robot' else [ci,share]
        for root in roots:
            p=root/name
            if p.is_file():bundle.add(p,arcname=str(p).lstrip('/'))
print('Backup:',backup,flush=True)
subprocess.run(['systemctl','stop','pr-ci@editor','pr-ci@worker','pr-ci@publisher'],check=True)
for rel in (stage/'files.json').read_text().splitlines():
    category,name=json.loads(rel)
    for root in ([robot] if category=='robot' else [ci,share]):
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(stage/category/name,target)
for root in [ci,share]:
    shutil.copytree(stage/'dist',root/'web/dist',dirs_exist_ok=True)
# Only change this profile's explicit scalar settings; validate TOML afterwards.
text=config.read_text()
import re
text=re.sub(r'^auth_mode\s*=.*\n','',text,flags=re.M)
text='auth_mode = "robot-session"\n'+text
text=re.sub(r'^public\s*=.*$', 'public = "http://119.8.233.58/pipeline"',text,flags=re.M)
text=re.sub(r'^editor\s*=.*\n','',text,flags=re.M)
text=text.replace('[urls]','[urls]\neditor = "http://119.8.233.58/submit/"')
for key in ('monitor','github_write','code_review','newlink','webhook'):
    text=re.sub(r'^'+key+r'\s*=.*\n','',text,flags=re.M)
text=text.replace('[features]','[features]\nmonitor = false\nwebhook = false\ngithub_write = false\ncode_review = false\nnewlink = false')
tomllib.loads(text);config.write_text(text)
drop=Path('/etc/systemd/system/swr-push-helper.service.d/same-site.conf')
drop.write_text('[Service]\nEnvironment=ROBOT_CI_BIND=127.0.0.1\nEnvironment=ROBOT_CI_PORT=18082\nEnvironment=ROBOT_CI_PUBLIC_ORIGIN=http://119.8.233.58\nEnvironment=GAMMA_E2E_PUBLIC_BASE=http://119.8.233.58/pipeline\n')
control=Path('/etc/systemd/system/pr-pipeline-control.service.d/same-site.conf')
control.write_text('[Service]\nEnvironment=PIPELINE_AUTH_MODE=robot-session\nEnvironment=PIPELINE_PUBLIC_BASE_URL=http://119.8.233.58/pipeline\nEnvironment=PIPELINE_EDITOR_URL=http://119.8.233.58/submit/\nEnvironment=PIPELINE_FEATURE_WEBHOOK=false\nEnvironment=PIPELINE_FEATURE_MONITOR=false\nEnvironment=PIPELINE_PUBLIC_READ=true\n')
for name in ('pr-e2e-share.conf','pr-pipeline-hub.conf'):
    site=Path('/etc/nginx/conf.d')/name
    if site.exists():site.rename(site.with_suffix('.disabled-same-site'))
shutil.copy2(stage/'same-site.nginx.conf','/etc/nginx/conf.d/pipeline-same-site.conf')
subprocess.run(['nginx','-t'],check=True)
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','restart','swr-push-helper','pr-pipeline-control'],check=True)
subprocess.run(['nginx','-s','reload'],check=True)
subprocess.run(['systemctl','disable','--now','pr-ci@monitor'],check=False)
subprocess.run(['systemctl','start','pr-ci@editor','pr-ci@worker','pr-ci@publisher'],check=True)
print('Same-site release installed; verify browser login and queue before acceptance.')
