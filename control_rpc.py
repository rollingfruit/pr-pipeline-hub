"""SSH-only RPC proxy; credentials stay on ECS, not in shell argv or PR images."""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

for line in Path('/etc/pr-pipeline-control.env').read_text().splitlines():
    if '=' in line:
        name, value = line.split('=', 1)
        os.environ[name] = value
payload = json.load(sys.stdin)
path = payload['path']
if not path.startswith('/internal/') and path not in {'/api/runs'}:
    raise ValueError('RPC path not allowed')
body = json.dumps(payload['body']).encode() if 'body' in payload else None
request = urllib.request.Request('http://127.0.0.1:8792'+path, body,
    {'Content-Type':'application/json', 'X-Worker-Token':os.environ['PIPELINE_WORKER_TOKEN'],
     'X-Pipeline-View-Token':os.environ['PIPELINE_VIEW_TOKEN']})
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        sys.stdout.buffer.write(response.read())
except urllib.error.HTTPError as error:
    print(json.dumps({'rpc_error': error.code, 'detail': error.read().decode()}))
    sys.exit(1)
