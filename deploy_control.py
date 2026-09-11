"""Deploy code and built assets only. Never upload local runtime secrets or evidence."""
import io
import subprocess
import tarfile
from pathlib import Path

root = Path(__file__).resolve().parent
ssh = '/mnt/c/Windows/System32/OpenSSH/ssh.exe'
files = [root / name for name in ['control_api.py', 'control_store.py', 'review_adapter.py',
    'review_policy.py', 'control_rpc.py', 'control_requirements.txt', 'share_viewer.py', 'pr_pipeline_hub.py',
    'e2e_catalog.py', 'deploy/install-control.py']]
files += [p for p in (root / 'web/dist').rglob('*') if p.is_file()]
if not (root / 'web/dist/index.html').exists():
    raise RuntimeError('Build web assets first')
buffer = io.BytesIO()
with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
    for file in files:
        archive.add(file, arcname=file.relative_to(root).as_posix())
subprocess.run([ssh, '-o', 'BatchMode=yes', 'root@119.8.233.58', 'tar -xzf - -C /opt/pr-e2e-share'], input=buffer.getvalue(), check=True)
subprocess.run([ssh, '-o', 'BatchMode=yes', 'root@119.8.233.58', '/usr/local/bin/python3.11 /opt/pr-e2e-share/deploy/install-control.py'], check=True)
