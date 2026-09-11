#!/usr/bin/env python3
"""Install a staged E04-E06 release after the shared queue is idle."""
from pathlib import Path
import json
import shutil
import subprocess
import tarfile
import time
import tomllib
import urllib.request

CONFIG = Path('/etc/pr-e2e/config.toml')
CI = Path('/opt/pr-pipeline-ci')
SHARE = Path('/opt/pr-e2e-share')
STAGE = Path('/var/tmp/e04-release')


def queue_is_idle():
    token = Path('/etc/pr-e2e/secrets/worker-token').read_text().strip()
    request = urllib.request.Request('http://127.0.0.1:8792/api/batches',
                                     headers={'X-Worker-Token': token})
    records = json.load(urllib.request.urlopen(request, timeout=15)).get('batches', [])
    active = [item['id'] for item in records if item.get('status') in {'queued', 'running'}]
    if active:
        raise RuntimeError('queue is not idle: ' + ', '.join(active))


def copy_tree(source, target):
    for item in source.rglob('*'):
        if item.is_file():
            destination = target / item.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)


def main():
    queue_is_idle()
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    backup = Path('/var/backups/pr-e2e') / ('e04-e06-' + stamp)
    backup.mkdir(parents=True, mode=0o700)
    shutil.copy2(CONFIG, backup / 'config.toml')
    for source, name in ((CI, 'ci.tgz'), (SHARE, 'share.tgz')):
        with tarfile.open(backup / name, 'w:gz') as archive:
            archive.add(source, arcname=source.name)

    subprocess.run(['systemctl', 'stop', 'pr-ci@worker', 'pr-ci@editor',
                    'pr-ci@publisher', 'pr-pipeline-control'], check=True)
    try:
        shutil.rmtree(STAGE, ignore_errors=True)
        (STAGE / 'hub').mkdir(parents=True)
        (STAGE / 'stack').mkdir()
        with tarfile.open('/var/tmp/e04-hub.tgz', 'r:gz') as archive:
            archive.extractall(STAGE / 'hub', filter='data')
        with tarfile.open('/var/tmp/e04-stack.tgz', 'r:gz') as archive:
            archive.extractall(STAGE / 'stack', filter='data')
        for root in (CI, SHARE):
            copy_tree(STAGE / 'hub', root)
            shutil.copytree('/var/tmp/e04-web/web/dist', root / 'web/dist', dirs_exist_ok=True)
        copy_tree(STAGE / 'stack', CI / 'stack')
        (CI / 'stack/fault-control.py').chmod(0o755)

        text = CONFIG.read_text()
        import re
        if re.search(r'^resilience\s*=', text, re.MULTILINE):
            text = re.sub(r'^resilience\s*=.*$', 'resilience = true', text, flags=re.MULTILINE)
        else:
            text = text.replace('[features]', '[features]\nresilience = true', 1)
        tomllib.loads(text)
        CONFIG.write_text(text)
        subprocess.run([str(CI / '.venv/bin/python'), str(CI / 'cloud_entry.py'),
                        '--config', str(CONFIG), 'check'], check=True)
    finally:
        subprocess.run(['systemctl', 'start', 'pr-pipeline-control', 'pr-ci@editor',
                        'pr-ci@worker', 'pr-ci@publisher'], check=True)
    print('backup:', backup)


if __name__ == '__main__':
    main()
