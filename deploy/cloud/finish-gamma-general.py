from pathlib import Path
import py_compile
import shutil
active=Path('/opt/pr-pipeline-ci/gamma_acceptance.py')
stage=Path('/opt/pr-pipeline-ci/gamma-general-stage')
if active.read_bytes() != (stage/'gamma_acceptance.py').read_bytes():
    raise SystemExit('Driver changed concurrently; not overwritten')
new=stage/'gamma_acceptance-final.py'
py_compile.compile(str(new),doraise=True)
shutil.copy2(active,stage/'gamma_acceptance-before-final.py')
shutil.copyfile(new,active)
print('Driver metadata and frozen-suite validation updated')
