"""Enable owned report writes and the restricted CI editor on the existing site."""
import os
from pathlib import Path
import pwd
import subprocess

account=pwd.getpwnam('prpipeline')
for path in ('/var/lib/pr-e2e-share','/var/lib/pr-e2e-share/runs','/var/lib/pr-e2e-share/snapshots'):
    os.chown(path,account.pw_uid,account.pw_gid)
dropin=Path('/etc/systemd/system/pr-pipeline-control.service.d/ci-worker.conf')
dropin.parent.mkdir(exist_ok=True)
dropin.write_text('[Service]\nReadWritePaths=/var/lib/pr-e2e-share\n'
    'Environment=PIPELINE_EDITOR_URL=http://119.8.233.58:8080/submit/\n'
    'Environment=PIPELINE_EXECUTION_LOCATION=ecs-liusong-ci\n'
    'Environment=PIPELINE_CLOUD_PROFILE=1\n')
site=Path('/etc/nginx/conf.d/pr-e2e-share.conf')
original=site.read_text()
marker='    listen 8080;'
include='    include /opt/pr-pipeline-ci/deploy/cloud/nginx-submit-ci.inc;'
if include not in original:
    if original.count(marker)!=1:raise ValueError('Unexpected existing Nginx server layout')
    site.write_text(original.replace(marker,marker+'\n'+include,1))
    result=subprocess.run(['nginx','-t'])
    if result.returncode:
        site.write_text(original)
        raise SystemExit('Nginx validation failed; site file restored')
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','restart','pr-pipeline-control'],check=True)
reload=subprocess.run(['systemctl','reload','nginx'])
if reload.returncode:
    # This host's existing unit cannot enter its reload namespace (226/NAMESPACE).
    subprocess.run(['nginx','-s','reload'],check=True)
print('Control report directory and restricted editor route enabled.')
