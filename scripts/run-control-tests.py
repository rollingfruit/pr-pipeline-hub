"""Run isolated-schema tests on ECS without printing the DSN."""
import os
from pathlib import Path
import runpy
import sys

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
for line in Path('/etc/pr-pipeline-control.env').read_text().splitlines():
    if line.startswith('PIPELINE_DATABASE_URL='):
        os.environ['PIPELINE_DATABASE_URL'] = line.split('=', 1)[1].strip('"\'')
sys.argv = ['test_control.py']
runpy.run_path(str(root / 'test_control.py'), run_name='__main__')
