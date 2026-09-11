"""Small independent authentication repair; never restart Robot CI or Worker."""
from pathlib import Path
import shutil
import subprocess
import time

stage = Path('/var/tmp/pipeline-session-adapter')
backup = Path('/var/backups/pr-e2e') / ('session-adapter-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
backup.mkdir(parents=True, mode=0o700)
targets = {}
for root in ('/opt/pr-pipeline-ci', '/opt/pr-e2e-share'):
    for name in ('robot_session.py', 'local_selection.py'):
        target = Path(root) / name
        if target.is_file():
            targets[target] = stage / name
config = Path('/etc/nginx/conf.d/pipeline-same-site.conf')
original = config.read_text()
if 'proxy_pass http://127.0.0.1:18082/api/auth/pipeline;' not in original:
    if 'proxy_pass http://127.0.0.1:8793/internal/session;' not in original:
        raise SystemExit('Unexpected authentication routing; inspect before deployment')
for target, source in targets.items():
    compile(source.read_text(), str(target), 'exec')
    saved = backup / str(target).lstrip('/')
    saved.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, saved)
shutil.copy2(config, backup / 'nginx.conf')
try:
    for target, source in targets.items():
        # Existing permissions/ownership are retained for service readability.
        target.write_bytes(source.read_bytes())
    updated = original.replace('proxy_pass http://127.0.0.1:18082/api/auth/pipeline;',
                               'proxy_pass http://127.0.0.1:8793/internal/session;')
    if 'location ~ ^/submit/(internal|webhooks)' not in updated:
        updated = updated.replace('    location /submit/ {',
            '    location ~ ^/submit/(internal|webhooks)(/|$) { return 404; }\n    location /submit/ {')
    if 'location @pipeline_auth_unavailable' not in updated:
        updated = updated.replace('    location = /_pipeline_auth {',
            '    error_page 500 = @pipeline_auth_unavailable;\n'
            '    location @pipeline_auth_unavailable {\n'
            '        default_type application/json;\n'
            '        return 503 \'{"error":"Authentication service unavailable; please retry later"}\';\n'
            '    }\n'
            '    location = /_pipeline_auth {')
    config.write_text(updated)
    subprocess.run(['nginx', '-t'], check=True)
    subprocess.run(['systemctl', 'restart', 'pr-ci@editor'], check=True)
    subprocess.run(['systemctl', 'restart', 'pr-pipeline-control'], check=True)
    import urllib.request, urllib.error
    for attempt in range(30):
        try:
            urllib.request.urlopen('http://127.0.0.1:8793/internal/session', timeout=2)
        except urllib.error.HTTPError as error:
            if error.code == 401:
                break
            raise
        except OSError:
            time.sleep(1)
    else:
        raise RuntimeError('Session adapter did not become ready')
    subprocess.run(['nginx', '-s', 'reload'], check=True)
except Exception:
    config.write_text(original)
    for target in targets:
        target.write_bytes((backup / str(target).lstrip('/')).read_bytes())
    subprocess.run(['systemctl', 'restart', 'pr-ci@editor'], check=False)
    subprocess.run(['systemctl', 'restart', 'pr-pipeline-control'], check=False)
    raise
print('Session adapter installed; backup:', backup)
