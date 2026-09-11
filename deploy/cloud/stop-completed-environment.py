"""Stop only an explicitly completed run's containers, retaining volumes."""
import json
from pathlib import Path
import re
import subprocess
import sys
run_id=sys.argv[1]
if not re.fullmatch('[a-zA-Z0-9-]+',run_id):raise SystemExit('Invalid run ID')
run=json.loads((Path('/var/lib/pr-e2e/data/runs')/run_id/'run.json').read_text())
if run['status']!='completed':raise SystemExit('Run must already be completed')
docker=['docker','-H','unix:///run/pr-e2e/docker.sock']
ids=subprocess.check_output(docker+['ps','-q','--filter','label=com.docker.compose.project=newlink-e2e-'+run_id],text=True).split()
if ids:subprocess.run(docker+['stop',*ids],check=True)
print('Stopped completed environment; volumes and reports retained')
