"""Bounded startup diagnostics. Trace socket connections, never request contents."""
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,'/opt/pr-pipeline-ci/stack')
import smoke_opencode

original=subprocess.run
def traced(command, **kwargs):
    kwargs['timeout']=40
    kwargs['env'].update(OPENCODE_PRINT_LOGS='true',OPENCODE_LOG_LEVEL='DEBUG')
    trace='/var/lib/pr-e2e/state/opencode-smoke/connections.log'
    command=['strace','-f','-e','trace=connect','-o',trace]+command
    key=Path('/var/lib/pr-e2e/state/opencode/modelarts-key').read_text().strip()
    try:
        result=original(command,**kwargs)
        print(result.stderr[-5000:].replace(key,'[REDACTED]'))
        return result
    except subprocess.TimeoutExpired as error:
        stderr=error.stderr or b''
        if isinstance(stderr,bytes):stderr=stderr.decode(errors='replace')
        print(stderr[-5000:].replace(key,'[REDACTED]'))
        raise
smoke_opencode.subprocess.run=traced
raise SystemExit(0 if smoke_opencode.run('/opt/pr-pipeline-tools/bin/opencode','/var/lib/pr-e2e/state/opencode-smoke',
                   '/var/lib/pr-e2e/state/opencode/opencode.json') else 1)
