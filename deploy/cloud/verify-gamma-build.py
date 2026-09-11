"""Operator acceptance of the real bridge using an existing immutable build."""
import json
import sys
from pathlib import Path

sys.path.insert(0, '/opt/swr-push-helper')
import gamma_real

job = json.loads(Path('/opt/swr-push-helper/logs/job-82cf0e6101c8.json').read_text())
if '--prepare-only' in sys.argv:
    print(gamma_real.prepare('verify-82cf0e6101c8', job['results'], job['optional_steps']))
else:
    ok, reason = gamma_real.run('verify-82cf0e6101c8', job['results'], job['optional_steps'],
        lambda line: print(line, flush=True), lambda record: print(json.dumps(record), flush=True), lambda: False)
    print('BRIDGE_RESULT', ok, reason, flush=True)
    sys.exit(0 if ok else 1)
