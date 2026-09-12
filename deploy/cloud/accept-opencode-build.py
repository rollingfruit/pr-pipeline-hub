"""Hand the verified CCE build to the normal Gamma rollout/acceptance driver."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--suites', nargs='+', choices=['E01', 'E02', 'E03', 'E04', 'E05', 'E06'],
                    default=['E04', 'E05', 'E06'])
args = parser.parse_args()
root = Path('/var/lib/pr-e2e/opencode-final-b8b3ac4')
build = json.loads((root / 'manifest.json').read_text())
tag = 'swr.cn-southwest-2.myhuaweicloud.com/public_ai/multica-server:e2e-final-b8b3ac4'
pinned = 'swr.cn-southwest-2.myhuaweicloud.com/public_ai/multica-server@sha256:2b96b912738b2028a0f6ae4c4f8164f50b9b62a4b00242897fce344a95561d2e'
image = json.loads(subprocess.check_output(['docker', '-H', 'unix:///run/pr-e2e/docker.sock', 'image', 'inspect', tag]))[0]
if image['Id'] != build['image_id'] or pinned not in image['RepoDigests'] or image['Config']['Labels']['org.opencontainers.image.revision'] != build['source_commit']:
    raise RuntimeError('Published build identity mismatch')
manifest = {'environment_id': '9253bcacca80', 'build_id': 'opencode-final-b8b3ac4', 'trigger_source': 'manual_cce_build',
    'suite_ids': list(dict.fromkeys(args.suites)), 'deploy': True, 'pinned_image': pinned, 'image_id': image['Id'],
    'result': {'service_id': 'multica-server', 'commit_sha': build['source_commit'], 'ok': True},
    'build_provenance': build}
path = Path('/var/lib/pr-e2e/build-inbox/opencode-final-b8b3ac4.json')
path.write_text(json.dumps(manifest, indent=2))
path.chmod(0o600)
print('Verified CCE build:', build['source_commit'], pinned, flush=True)
sys.exit(subprocess.call(['/usr/local/bin/python3.11', '/opt/pr-pipeline-ci/gamma_acceptance.py',
    '--environment-id', manifest['environment_id'], '--build-manifest', str(path), '--suites', *manifest['suite_ids']]))
