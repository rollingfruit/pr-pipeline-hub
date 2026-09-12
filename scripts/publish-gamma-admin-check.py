"""Publish an actual administrative diagnostic, explicitly separate from E2E results."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import sys
from urllib.request import Request, urlopen

run_id = sys.argv[1]
if not re.fullmatch(r'admin-check-[0-9]{8}-[0-9]{6}-[a-f0-9]{6}', run_id):
    raise SystemExit('Invalid administrative diagnostic ID')
source = Path('/var/lib/pr-gamma-admin-checks') / run_id / 'report.json'
report = json.loads(source.read_text())
if report['id'] != run_id or report.get('kind') != 'administrative_diagnostic':
    raise SystemExit('Mismatched diagnostic report')
root = Path('/var/lib/pr-e2e-share/runs') / run_id
root.mkdir(mode=0o750)
artifact = root / 'artifacts/current/admin/report.json'
artifact.parent.mkdir(parents=True)
artifact.write_bytes(source.read_bytes())
checks = [('ordinary-user', '普通账号执行', report.get('test_roles') == 'system_user'),
          ('deactivate', '管理员停用与状态核对', report.get('cleanup', {}).get('account_inactive_verified') is True),
          ('session', '原会话失效与登录拒绝', report.get('session_invalidated') is True and report.get('login_rejected') is True),
          ('idempotency', '重复清理与活动残留核对', report.get('second_cleanup', {}).get('already_inactive') is True
           and report.get('active_residuals') == [])]
run = {'id': run_id, 'title': 'dev-gamma 管理员账号清理诊断（非 E2E 验收）',
       'created_at': datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat(),
       'status': 'completed', 'conclusion': 'success' if report['status'] == 'passed' else 'error',
       'kind': 'administrative_diagnostic', 'profile': 'admin-cleanup', 'source_mode': 'environment',
       'repo': 'dev-gamma', 'diagnostic': True, 'full_acceptance': False, 'requested_by': 'operator',
       'summary': '管理员清理通道实测；普通账号未提权，自助停用仍关闭。本记录不计入 E01-E06 或正式30轮。',
       'suites': [], 'test_results': [], 'review': {'status': 'disabled', 'findings': []},
       'github': {'state': 'disabled'}, 'cleanup': {'status': report['status'], 'active_residuals': report.get('active_residuals')},
       'stages': [{'id': key, 'name': label, 'status': 'completed', 'conclusion': 'success' if passed else 'failure'}
                  for key, label, passed in checks],
       'archive_manifest': [{'path': 'artifacts/current/admin/report.json', 'bytes': artifact.stat().st_size,
                             'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()}]}
for key, label, passed in checks:
    (root / (key + '.log')).write_text(label + ': ' + ('passed' if passed else 'failed') + '\n' +
                                     json.dumps(report, ensure_ascii=False, indent=2))
(root / 'run.json').write_text(json.dumps(run, ensure_ascii=False, indent=2))
account = pwd.getpwnam('prpipeline')
for folder, _, files in os.walk(root):
    os.chown(folder, account.pw_uid, account.pw_gid)
    os.chmod(folder, 0o750)
    for name in files:
        os.chown(Path(folder) / name, account.pw_uid, account.pw_gid)
        os.chmod(Path(folder) / name, 0o640)
print('http://119.8.233.58/pipeline/runs/' + run_id)
token = Path('/etc/pr-e2e/secrets/worker-token').read_text().strip()
with urlopen(Request('http://127.0.0.1:8792/api/runs/' + run_id,
                     headers={'X-Worker-Token': token}), timeout=15) as response:
    saved = json.load(response)
if saved.get('id') != run_id:
    raise RuntimeError('Published administrative report could not be resolved by Hub')
print(json.dumps({'hub_verified': True, 'conclusion': saved.get('conclusion')}))
