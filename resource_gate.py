"""Admission checks for the isolated CI worker; never assume host isolation."""
import os
from pathlib import Path
import shutil
import subprocess


def inspect():
    if os.environ.get('PIPELINE_RESOURCE_GATE')!='true':return {'ready':True,'enabled':False}
    try:
        return _inspect()
    except (OSError, ValueError, KeyError) as exc:
        return {'enabled':True,'ready':False,'status':'waiting_resources',
                'reasons':['resource_probe_failed'],'error_type':type(exc).__name__}


def _inspect():
    failures=[]
    info=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    available=int(info['MemAvailable'].split()[0])*1024
    root=Path(os.environ['E2E_STATE_DIR'])
    free=shutil.disk_usage(root).free
    if available < int(os.getenv('PIPELINE_MIN_MEMORY_GIB','12'))*1024**3:failures.append('available_memory')
    if free < int(os.getenv('PIPELINE_MIN_DISK_GIB','60'))*1024**3:failures.append('free_disk')
    group='/pr.slice/pr-e2e.slice'
    try:
        memory=int(Path('/sys/fs/cgroup/memory'+group+'/memory.limit_in_bytes').read_text())
        quota=int(Path('/sys/fs/cgroup/cpu'+group+'/cpu.cfs_quota_us').read_text())
        period=int(Path('/sys/fs/cgroup/cpu'+group+'/cpu.cfs_period_us').read_text())
        if memory!=10*1024**3 or quota!=2*period:failures.append('resource_limits')
        own=Path('/proc/self/cgroup').read_text()
        if not any(line.split(':')[-1].startswith(group+'/') for line in own.splitlines() if ':memory:' in line):
            failures.append('worker_outside_resource_group')
    except (OSError,ValueError):failures.append('cgroup_unavailable')
    try:
        probe=subprocess.run(['docker','info','--format','{{.DockerRootDir}}'],capture_output=True,text=True,timeout=15)
        if probe.returncode or probe.stdout.strip()!='/var/lib/pr-e2e-docker':failures.append('wrong_docker_engine')
    except (OSError,subprocess.TimeoutExpired):failures.append('docker_unavailable')
    return {'enabled':True,'ready':not failures,'status':'ready' if not failures else 'waiting_resources',
            'available_memory_bytes':available,'free_disk_bytes':free,'reasons':failures}
