"""Create the explicit local image baseline; never query or deploy CCE."""
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,'/opt/pr-pipeline-ci/stack')
import stack

output=Path('/etc/pr-e2e/artifact-baseline.json')
if output.exists():
    raise SystemExit('Baseline exists; review versions before replacing it')
records={}
for service,(repo,_,_) in stack.SERVICES.items():
    available=[]
    for file in Path('/var/lib/pr-e2e/state/build-contexts').glob(repo+'-*/build.json'):
        record=json.loads(file.read_text())
        if record.get('exit_code')==0 and record.get('image_id'):
            available.append((file.stat().st_mtime,record))
    if not available:raise SystemExit('Missing baseline: '+repo)
    record=max(available,key=lambda r:r[0])[1]
    actual=subprocess.check_output(['docker','-H','unix:///run/pr-e2e/docker.sock','image','inspect','--format','{{.Id}}',record['image_id']],text=True).strip()
    if actual!=record['image_id']:raise SystemExit('Image mismatch: '+repo)
    records[service]={'repo':'rollingfruit/'+repo,'source_sha':record['source_sha'],'image_id':actual}
    if repo=='mattermost' and record['source_sha'].startswith('e4eded6'):
        records[service]['limitation']='Unmerged CI adapter idempotency fix; not the upstream main image'
output.write_text(json.dumps(records,indent=2))
output.chmod(0o640)
print(json.dumps(records,indent=2))
