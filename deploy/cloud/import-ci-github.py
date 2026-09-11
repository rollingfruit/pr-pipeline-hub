"""Receive the explicitly authorized local gh token on SSH stdin, never argv."""
import os
from pathlib import Path
import pwd
import sys
import tempfile
import tomllib


def main():
    token = sys.stdin.read(16384).strip()
    if not token or any(c.isspace() for c in token):
        raise ValueError('Missing or malformed credential; existing configuration unchanged')
    config = Path('/etc/pr-e2e/config.toml')
    text = config.read_text()
    parsed = tomllib.loads(text)
    if parsed['features'].get('code_review'):
        raise ValueError('Disable optional code review before importing this profile')
    target = Path('/etc/pr-e2e/secrets/github-token')
    setting = 'github_token = "/etc/pr-e2e/secrets/github-token"'
    lines = text.splitlines()
    matches = [i for i, line in enumerate(lines) if line.lstrip('# ').startswith('github_token =')]
    if len(matches) != 1:
        raise ValueError('Expected one GitHub credential setting')
    lines[matches[0]] = setting
    updated = '\n'.join(lines) + '\n'
    if tomllib.loads(updated)['secrets']['github_token'] != str(target):
        raise ValueError('Unexpected credential section')
    gid = pwd.getpwnam('pr-e2e').pw_gid
    for path, value in ((target, token + '\n'), (config, updated)):
        fd, name = tempfile.mkstemp(dir=path.parent, prefix='.credential-update-')
        try:
            os.fchmod(fd, 0o640)
            os.fchown(fd, 0, gid)
            with os.fdopen(fd, 'w') as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    print('GitHub credential configured; secret not printed; code review remains disabled.')


if __name__ == '__main__':
    main()
