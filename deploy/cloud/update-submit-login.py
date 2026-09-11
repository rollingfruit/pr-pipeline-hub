"""Rotate only the web editor password. Run on CI; secret arrives on stdin."""
import os
from pathlib import Path
import shutil
import sys
import time

path = Path('/etc/pr-e2e/secrets/submit-password')
secret = sys.stdin.read(4096).strip()
if not secret or '\n' in secret or '\r' in secret:
    raise SystemExit('One nonempty password is required')
info = path.stat()
backup = Path('/var/backups/pr-e2e') / ('submit-password-' + str(time.time_ns()))
shutil.copy2(path, backup)
backup.chmod(0o600)
temporary = path.with_name('.submit-password-' + str(time.time_ns()))
fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream:
    stream.write(secret + '\n')
os.chown(temporary, info.st_uid, info.st_gid)
temporary.chmod(info.st_mode & 0o777)
os.replace(temporary, path)
print('Web editor password rotated; SSH credentials unchanged.')
