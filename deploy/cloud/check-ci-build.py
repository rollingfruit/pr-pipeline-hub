"""Run one real baseline build diagnostic; never represent it as PR acceptance."""
import os
import argparse
import fcntl
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, '/opt/pr-pipeline-ci')
from cloud_config import load, activate

cfg=load('/etc/pr-e2e/config.toml','worker',True)
activate(cfg,'worker')
os.environ['DOCKER_CONFIG']='/var/lib/pr-e2e/state/docker-config'
os.environ['PATH']='/var/lib/pr-e2e/state/tools/go1.26.5/bin:/var/lib/pr-e2e/state/tools/node24.18.0/bin:'+os.environ['PATH']
os.environ['GOPROXY']='https://goproxy.cn,direct'
parser=argparse.ArgumentParser()
parser.add_argument('--service',default='governance')
parser.add_argument('--source')
parser.add_argument('--revision',default='HEAD')
args=parser.parse_args()
with (Path(cfg['paths']['state'])/'environment.lock').open('a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    command=[sys.executable,cfg['paths']['stack']+'/build-service.py',args.service,'--revision',args.revision]
    if args.source:command+=['--source',args.source]
    result=subprocess.run(command,stdin=subprocess.DEVNULL)
raise SystemExit(result.returncode)
