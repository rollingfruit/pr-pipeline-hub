"""Allow OpenCode to read only the dedicated external E2E fixture directory."""
import fcntl
import json
import os
from pathlib import Path
import shutil
from datetime import datetime, timezone

state = Path('/var/lib/pr-e2e/state')
with (state / 'environment.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    settings = json.loads((state / 'settings.json').read_text())
    fixture = Path(settings['TEST_WORKSPACE']).resolve()
    assert fixture == state / 'agent-workspace', 'Unexpected fixture directory'
    config = Path(settings['OPENCODE_CONFIG']).resolve()
    assert config == state / 'opencode/opencode.json', 'Unexpected model config'
    value = json.loads(config.read_text())
    permission = value.setdefault('permission', {})
    permission['external_directory'] = {
        '*': 'deny', str(fixture): 'allow', str(fixture) + '/**': 'allow'
    }
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    shutil.copy2(config, config.with_name(config.name + '.before-' + stamp))
    temporary = config.with_suffix('.next')
    shutil.copy2(config, temporary)
    temporary.write_text(json.dumps(value, indent=2))
    os.chown(temporary, config.stat().st_uid, config.stat().st_gid)
    temporary.chmod(0o600)
    os.replace(temporary, config)
    print('Updated dedicated E2E fixture permission; model credentials unchanged.')
