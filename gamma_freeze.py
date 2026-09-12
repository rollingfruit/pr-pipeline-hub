"""Root-owned execution inputs, copied once and validated before each round."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(root):
    root = Path(root)
    return {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()
            and '__pycache__' not in p.parts}


def environment(access):
    deployments = access.resource('deployments')['items']
    template = {d['metadata']['name']: {'uid': d['metadata']['uid'], 'template': d['spec']['template']} for d in deployments}
    # Only digests leave memory. Secret values and full templates are never published.
    config = {}
    for kind in ('configmaps', 'secrets'):
        config[kind] = {r['metadata']['name']: {k: r.get(k) for k in ('data', 'binaryData', 'type')}
                        for r in access.resource(kind)['items']
                        if not r['metadata']['name'].startswith(('sh.helm.release.', 'kube-root-ca.'))
                        and r.get('type') != 'kubernetes.io/service-account-token'}
    pods = access.resource('pods')['items']
    actual_images = sorted({c.get('imageID', '') for p in pods if p['metadata'].get('ownerReferences')
                            and not p['metadata'].get('deletionTimestamp')
                            for c in p.get('status', {}).get('containerStatuses', [])})
    value = {'deployments': template, 'config': config, 'actual_images': actual_images}
    return {'fingerprint': hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest(),
            'images': {d['metadata']['name']: [c['image'] for c in d['spec']['template']['spec']['containers']] for d in deployments}}


def create(root, access):
    target = Path(root) / 'frozen'
    target.mkdir(mode=0o755)
    source = Path('/opt/pr-pipeline-ci')
    for name in ('gamma_acceptance.py', 'gamma_access.py', 'gamma_rollout.py', 'gamma_readiness.py',
                 'gamma_cleanup.py', 'gamma_admin.py', 'gamma_lease.py', 'gamma_freeze.py', 'control_client.py', 'e2e_catalog.py'):
        shutil.copy2(source / name, target / name)
    shutil.copytree(source / 'stack', target / 'stack', ignore=shutil.ignore_patterns(
        'node_modules', '__pycache__', '.git', 'results', 'test-results', '*.log', '.env'))
    shutil.copytree('/var/lib/pr-e2e/state/playwright/node_modules', target / 'node_modules', symlinks=True)
    settings = json.loads(Path('/var/lib/pr-e2e/state/settings.json').read_text())
    config = Path(settings['OPENCODE_CONFIG']).resolve()
    # Preserve key-file references without placing their contents in the bundle.
    manifest = {'environment': environment(access), 'files': inventory(target),
                'model': settings['OPENCODE_MODEL'], 'config_path': str(config), 'config_sha256': digest(config),
                'credential_fingerprint': digest(config.parent / 'modelarts-key'),
                'cli_path': str(Path('/opt/pr-pipeline-tools/bin/opencode').resolve())}
    manifest['cli_sha256'] = digest(manifest['cli_path'])
    manifest['settings_sha256'] = digest('/var/lib/pr-e2e/state/settings.json')
    command = ('kubectl -n ' + shlex.quote(access.namespace) +
               ' exec deployment/multica-server -- sha256sum /opt/ai/multica-server/connector-assets/multica-linux-amd64')
    manifest['daemon_sha256'] = access.remote(command).split()[0]
    manifest['runtime_files'] = {}
    for directory in ('/opt/pr-pipeline-tools/opencode', '/var/lib/pr-e2e/.cache/ms-playwright',
                      '/opt/pr-pipeline-ci/.venv/lib'):
        manifest['runtime_files'][directory] = inventory(directory)
    manifest['executables'] = {str(Path(p).resolve()): digest(p) for p in (
        '/usr/local/bin/python3.11', '/opt/pr-pipeline-ci/.venv/bin/python',
        '/var/lib/pr-e2e/state/tools/node24.18.0/bin/node')}
    for folder, dirs, files in os.walk(target):
        os.chmod(folder, 0o555)
        for name in files:
            p = Path(folder) / name
            if not p.is_symlink():
                p.chmod(0o555 if p.stat().st_mode & 0o111 else 0o444)
    path = Path(root) / 'freeze.json'
    path.write_text(json.dumps(manifest, sort_keys=True))
    path.chmod(0o600)
    return manifest


def verify(root, access):
    root = Path(root)
    expected = json.loads((root / 'freeze.json').read_text())
    if inventory(root / 'frozen') != expected['files']:
        raise RuntimeError('Frozen harness/dependencies changed; start a new experiment')
    if environment(access)['fingerprint'] != expected['environment']['fingerprint']:
        raise RuntimeError('Frozen environment changed; automatic overwrite refused')
    config = Path(expected['config_path'])
    if digest('/var/lib/pr-e2e/state/settings.json') != expected['settings_sha256']:
        raise RuntimeError('Execution settings changed; start a new experiment')
    command = ('kubectl -n ' + shlex.quote(access.namespace) +
               ' exec deployment/multica-server -- sha256sum /opt/ai/multica-server/connector-assets/multica-linux-amd64')
    if access.remote(command).split()[0] != expected['daemon_sha256']:
        raise RuntimeError('Published Daemon binary changed')
    if digest(config) != expected['config_sha256'] or digest(config.parent / 'modelarts-key') != expected['credential_fingerprint']:
        raise RuntimeError('Model configuration or credential changed')
    if digest(expected['cli_path']) != expected['cli_sha256']:
        raise RuntimeError('OpenCode executable changed')
    if any(inventory(directory) != files for directory, files in expected['runtime_files'].items()):
        raise RuntimeError('Frozen execution runtime changed')
    if any(digest(path) != sha for path, sha in expected['executables'].items()):
        raise RuntimeError('Execution interpreter changed')
    return expected
