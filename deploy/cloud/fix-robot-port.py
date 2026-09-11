"""Move Robot CI away from the Compose-reserved Multica port."""
import json
from pathlib import Path
import shutil
import subprocess
import time

stamp=str(int(time.time()))
config=Path('/opt/swr-push-helper/config.json')
shutil.copy2(config,config.with_name('config.before-port-'+stamp+'.json'))
value=json.loads(config.read_text());value['host']='127.0.0.1';value['port']=18082
config.write_text(json.dumps(value,indent=2,ensure_ascii=False))
for file in ['/etc/systemd/system/swr-push-helper.service.d/same-site.conf','/etc/nginx/conf.d/pipeline-same-site.conf']:
    p=Path(file);p.write_text(p.read_text().replace('18080','18082'))
path=Path('/etc/pr-e2e/config.toml');text=path.read_text()
if 'robot_auth_url =' not in text:text='robot_auth_url = "http://127.0.0.1:18082/api/auth/pipeline"\n'+text
path.write_text(text)
drop=Path('/etc/systemd/system/pr-pipeline-control.service.d/same-site.conf')
text=drop.read_text()
if 'PIPELINE_ROBOT_AUTH_URL=' not in text:text+='Environment=PIPELINE_ROBOT_AUTH_URL=http://127.0.0.1:18082/api/auth/pipeline\n'
drop.write_text(text)
subprocess.run(['nginx','-t'],check=True)
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','restart','swr-push-helper','pr-pipeline-control','pr-ci@editor'],check=True)
subprocess.run(['nginx','-s','reload'],check=True)
