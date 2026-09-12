import json
from pathlib import Path
import sys
sys.path.insert(0, '/opt/pr-pipeline-ci')
from gamma_access import GammaAccess
from gamma_cleanup import verify_runtime_inactive
access = GammaAccess('a5932430eb2f')
try:
    access.connect()
    root = Path('/var/lib/pr-gamma-executor/diagnostics/gamma-check-20260912-121147-c0d9ee')
    print(json.dumps({'runtime_inventory': verify_runtime_inactive(root, access)}))
finally:
    access.close()
