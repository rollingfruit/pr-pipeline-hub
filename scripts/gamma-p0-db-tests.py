"""Run queue fault tests in a disposable schema using the installed DB credentials."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, '/opt/gamma-p0-validation/hub')
for line in Path('/etc/pr-pipeline-control.env').read_text().splitlines():
    if line.startswith('PIPELINE_DATABASE_URL='):
        os.environ['GAMMA_TEST_DSN'] = line.split('=', 1)[1].strip().strip('"').strip("'")
suite = unittest.defaultTestLoader.discover('/opt/gamma-p0-validation/hub/tests', pattern='test_gamma_postgres.py')
raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
