"""Read-only administrative capability check. Never prints passwords or tokens."""
import json
import sys
from pathlib import Path

sys.path.insert(0, '/opt/gamma-p0-validation/hub')
sys.path.append('/opt/pr-pipeline-ci')
from gamma_access import GammaAccess
from gamma_admin import MattermostAdmin

access = GammaAccess('a5932430eb2f')
try:
    access.connect()
    admin = MattermostAdmin(access)
    private = Path('/var/lib/pr-e2e/gamma-diagnostics/gamma-check-20260911-205917-64cccb/private')
    cfg = json.loads((private / 'settings.json').read_text())
    boot = json.loads((private / 'bootstrap.json').read_text())
    expected = {'user_id': boot['user_id'], 'username': cfg['TEST_ADMIN_USER'], 'email': cfg['TEST_ADMIN_EMAIL']}
    user = admin.fixture(expected)
    print(json.dumps({'administrative_access_verified': True, 'method': 'mattermost_mmctl_local',
                      'test_account_roles': user['roles'], 'secrets_exported': False}))
finally:
    access.close()
