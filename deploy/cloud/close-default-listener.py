"""Retire the pre-existing default 8080 static site from public interfaces."""
from pathlib import Path
import shutil
import subprocess
import time

path=Path('/etc/nginx/nginx.conf')
text=path.read_text()
shutil.copy2(path,path.with_name('nginx.conf.before-same-site-'+str(int(time.time()))))
text=text.replace('listen       8080;', 'listen       127.0.0.1:18081;')
text=text.replace('listen       [::]:8080;', '# Former public IPv6 static listener retired.')
path.write_text(text)
subprocess.run(['nginx','-t'],check=True)
subprocess.run(['nginx','-s','reload'],check=True)
