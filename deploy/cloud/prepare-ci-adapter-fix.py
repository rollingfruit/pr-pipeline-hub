"""Create a local, explicitly unmerged test-adapter revision; never push GitHub."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

root=Path('/var/lib/pr-e2e/state/adapter-fixes/mattermost-idempotency')
if root.exists():raise SystemExit('Adapter checkout exists; inspect it before repeating')
root.parent.mkdir(parents=True,exist_ok=True)
subprocess.run(['git','clone','--no-hardlinks','/var/lib/pr-e2e/workspace/mattermost',str(root)],check=True)
base=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
subprocess.run(['git','-C',str(root),'switch','-c','ci/e2e-mattermost-idempotency'],check=True)
patch=Path('/opt/pr-pipeline-ci/deploy/cloud/mattermost-header.patch')
subprocess.run(['git','-C',str(root),'apply','--check',str(patch)],check=True)
subprocess.run(['git','-C',str(root),'apply',str(patch)],check=True)
relative='webapp/channels/src/components/agents_manage/'
shutil.copyfile('/opt/pr-pipeline-ci/deploy/cloud/adapter-api.test.ts',root/relative/'api.test.ts')
subprocess.run(['git','-C',str(root),'add',relative+'api.ts',relative+'api.test.ts'],check=True)
subprocess.run(['git','-C',str(root),'-c','user.name=CI E2E Adapter',
                '-c','user.email=ci-e2e@localhost','commit','-m','fix(test-adapter): send managed-agent creation idempotency key'],check=True)
sha=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
record={'scope':'unmerged-test-adapter-fix','published':False,'base_sha':base,'source_sha':sha,
        'patch_sha256':hashlib.sha256(patch.read_bytes()).hexdigest(),'checkout':str(root)}
(root.parent/'mattermost-idempotency.json').write_text(json.dumps(record,indent=2))
print(json.dumps(record))
