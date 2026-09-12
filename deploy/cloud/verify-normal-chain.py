"""Verify archived Gamma evidence without rewriting historical conclusions."""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, '/opt/pr-pipeline-ci')
from e2e_catalog import validate_result

root = Path('/var/lib/pr-e2e-share/runs') / sys.argv[1]
run = json.loads((root / 'run.json').read_text())
bad = []
for item in run.get('archive_manifest', []):
    path = (root / item['path']).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
        bad.append(item['path'])
results = {}
selected = [item['id'] for item in run.get('suites', [])]
if not selected or not run.get('archive_manifest'):
    raise ValueError('Missing selected suites or archived evidence')
for suite in selected:
    if suite not in {'E01', 'E02', 'E03', 'E04', 'E05', 'E06'}:
        raise ValueError('Unknown selected suite: ' + suite)
    path = root / 'artifacts/current' / suite / 'evidence.json'
    try:
        payload = json.loads(path.read_text())
        validate_result(payload, suite)
        results[suite] = 'passed'
    except (OSError, ValueError) as error:
        results[suite] = str(error)
print(json.dumps({'id': run['id'], 'status': run['status'], 'conclusion': run.get('conclusion'),
    'stale': run.get('stale', False), 'suites': results, 'artifact_count': len(run.get('archive_manifest', [])),
    'artifact_hash_failures': bad, 'environment_status': run.get('environment_status'),
    'diagnostic': run.get('diagnostic'), 'images': run.get('image_manifest')}, ensure_ascii=False, indent=2))
sys.exit(0 if run['status'] == 'completed' and run.get('conclusion') == 'success'
         and not run.get('stale') and not bad and set(results.values()) == {'passed'} else 1)
