"""Build the trusted packaging sandbox on the isolated engine only."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

root=Path('/opt/pr-pipeline-ci/deploy/cloud')
env={**os.environ,'DOCKER_HOST':'unix:///run/pr-e2e/docker.sock',
     'DOCKER_CONFIG':'/var/lib/pr-e2e/state/docker-config'}
with tempfile.TemporaryDirectory() as tmp:
    context=Path(tmp)
    for name in ('Dockerfile.cce-builder','cce-builder-entry.sh'):
        shutil.copyfile(root/name,context/('Dockerfile' if name.startswith('Dockerfile') else name))
    shutil.copyfile('/usr/bin/docker',context/'docker')
    shutil.copyfile('/var/lib/pr-e2e/state/docker-config/cli-plugins/docker-buildx',context/'docker-buildx')
    subprocess.run(['docker','build','--progress=plain','-t','local/pr-e2e-cce-builder:20260910',str(context)],env=env,check=True)
