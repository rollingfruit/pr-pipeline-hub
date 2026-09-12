"""Build the reviewed OpenCode fix with Multica's existing CCE entry point."""
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tarfile

commit = sys.argv[1]
if not re.fullmatch('[0-9a-f]{40}', commit):
    raise ValueError('Frozen source commit required')
root = Path('/var/lib/pr-e2e') / ('opencode-final-' + commit[:7])
archive = Path('/var/lib/pr-e2e') / ('opencode-final-source-' + commit[:7] + '.tar.gz')
root.mkdir(exist_ok=False)
source = root / 'source'
source.mkdir()
with tarfile.open(archive) as data:
    data.extractall(source, filter='data')
env = {**os.environ, 'PATH': '/var/lib/pr-e2e/state/tools/go1.26.5/bin:' + os.environ['PATH'],
    'GOMODCACHE': '/var/lib/pr-e2e/go/pkg/mod', 'GOCACHE': '/var/lib/pr-e2e/.cache/go-build',
    'GOPROXY': 'https://goproxy.cn,https://proxy.golang.org,direct', 'GOTOOLCHAIN': 'local', 'GOMAXPROCS': '2',
    'DOCKER_HOST': 'unix:///run/pr-e2e/docker.sock', 'DEPLOY_CONFIG': '/dev/null',
    'GO_IMAGE': 'local/ai-go-toolchain:1.26.5', 'SOURCE_COMMIT': commit, 'SKIP_FILESERVER_LFS': '1',
    'MULTICA_SERVER_IMAGE': 'local/multica-server:opencode-final-' + commit[:7],
    'MULTICA_OUTPUT_DIR': str(root / 'output'), 'CCE_GIT_HASH': commit[:7]}
for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'PIPELINE_WORKER_TOKEN', 'PIPELINE_DATABASE_URL'):
    env.pop(key, None)
manifest = {'source_commit': commit, 'source_archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
    'build_entry': 'build/package/build.sh pack', 'go_image': env['GO_IMAGE'], 'image': env['MULTICA_SERVER_IMAGE']}
def run(command, log, timeout):
    print('START', log, flush=True)
    with (root / log).open('w') as output:
        result = subprocess.run(command, cwd=source, env=env, stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
    print('END', log, result.returncode, flush=True)
    if result.returncode:
        raise RuntimeError('See ' + str(root / log))
run(['go', 'test', '-p', '1', './pkg/agent', './internal/daemon', '-run', 'TestOpencode|TestProviderUsesIMFinalOutputOnly', '-count=1'], 'unit.log', 900)
run(['bash', 'build/package/build.sh', 'pack'], 'build.log', 2400)
manifest['image_id'] = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', env['MULTICA_SERVER_IMAGE']], env=env, text=True).strip()
(root / 'manifest.json').write_text(json.dumps(manifest, indent=2))
print(json.dumps(manifest), flush=True)
