"""Extract verified build tool archives without replacing system tools."""
from pathlib import Path
import tarfile

root = Path('/var/lib/pr-e2e/state')
for archive, name, top in (
    ('go1.25.9.linux-amd64.tar.gz', 'go1.25.9', 'go'),
    ('go1.26.5.linux-amd64.tar.gz', 'go1.26.5', 'go'),
    ('node-v24.18.0-linux-x64.tar.gz', 'node24.18.0', 'node-v24.18.0-linux-x64'),
):
    target = root / 'tools' / name
    if target.exists():
        print(name + ': retained')
        continue
    staging = root / 'tools' / (name + '.staging')
    staging.mkdir(parents=True, exist_ok=False)
    with tarfile.open(root / 'build-inputs' / archive) as bundle:
        bundle.extractall(staging, filter='data')
    (staging / top).rename(target)
    staging.rmdir()
    print(name + ': installed')
