"""Promote a verified CCE image and its own bundled Daemon together on CI."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime,timezone

parser=argparse.ArgumentParser();parser.add_argument('sha');args=parser.parse_args()
if not re.fullmatch('[0-9a-f]{40}',args.sha):raise SystemExit('Full source SHA required')
state=Path('/var/lib/pr-e2e/state')
docker=['docker','-H','unix:///run/pr-e2e/docker.sock']
record=json.loads((state/'build-contexts'/('multica-aiwelink-'+args.sha[:12])/'build.json').read_text())
assert record['source_sha']==args.sha and record['exit_code']==0
image=record['image_id']
metadata=json.loads(subprocess.check_output(docker+['image','inspect',image],text=True))[0]
assert metadata['Id']==image and metadata['Config']['Labels']['org.opencontainers.image.revision']==args.sha
with (state/'environment.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 settings=json.loads((state/'settings.json').read_text())
 profile=settings.get('LOCAL_DAEMON_PROFILE','')
 if profile:
  if not profile.startswith('pr-e2e-'):raise SystemExit('Not a dedicated test daemon')
  subprocess.run(['runuser','-u','pr-e2e','--','env','HOME='+str(state/'daemon-home'),'/opt/pr-pipeline-tools/multica','daemon','stop','--profile',profile],check=True,timeout=45)
 name='pr-e2e-extract-'+args.sha[:12]
 target=Path('/opt/pr-pipeline-tools/multica-'+args.sha[:12])
 subprocess.run(docker+['create','--name',name,image],check=True,stdout=subprocess.DEVNULL)
 try:subprocess.run(docker+['cp',name+':/opt/ai/multica-server/bin/multica',str(target)],check=True)
 finally:subprocess.run(docker+['rm',name],check=True,stdout=subprocess.DEVNULL)
 target.chmod(0o755)
 with target.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 installed=Path('/opt/pr-pipeline-tools/multica')
 shutil.copy2(installed,installed.with_name('multica-before-'+stamp))
 temporary=installed.with_suffix('.next');shutil.copy2(target,temporary);os.replace(temporary,installed)
 baseline=Path('/etc/pr-e2e/artifact-baseline.json');shutil.copy2(baseline,baseline.with_suffix('.before-'+stamp+'.json'))
 value=json.loads(baseline.read_text());value['multica-server']={'repo':'rollingfruit/multica-aiwelink','source_sha':args.sha,'image_id':image,
  'daemon':{'sha256':digest,'extracted_from_image':image,'path':str(installed)}}
 baseline.write_text(json.dumps(value,indent=2))
 proof={'source_sha':args.sha,'image_id':image,'daemon_sha256':digest,'at':stamp}
 (state/'multica-runtime-alignment.json').write_text(json.dumps(proof,indent=2))
 print(json.dumps(proof))
