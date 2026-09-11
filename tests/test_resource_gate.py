import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import resource_gate


class ResourceGateTests(unittest.TestCase):
    def probe(self, memory=13, disk=80, quota=200000, own=True, engine=True):
        values={
            '/proc/meminfo':f'MemAvailable: {memory*1024*1024} kB\n',
            '/sys/fs/cgroup/memory/pr.slice/pr-e2e.slice/memory.limit_in_bytes':str(10*1024**3),
            '/sys/fs/cgroup/cpu/pr.slice/pr-e2e.slice/cpu.cfs_quota_us':str(quota),
            '/sys/fs/cgroup/cpu/pr.slice/pr-e2e.slice/cpu.cfs_period_us':'100000',
            '/proc/self/cgroup':'3:memory:/pr.slice/pr-e2e.slice/worker\n' if own else '3:memory:/system.slice/worker\n',
        }
        with patch.dict(os.environ,{'PIPELINE_RESOURCE_GATE':'true','E2E_STATE_DIR':'/tmp'},clear=True), \
             patch.object(resource_gate.Path,'read_text',lambda p:values[str(p)]), \
             patch.object(resource_gate.shutil,'disk_usage',return_value=SimpleNamespace(free=disk*1024**3)), \
             patch.object(resource_gate.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='/var/lib/pr-e2e-docker' if engine else '/var/lib/docker')):
            return resource_gate.inspect()

    def test_ready(self):
        self.assertTrue(self.probe()['ready'])

    def test_admission_thresholds(self):
        self.assertTrue(self.probe(memory=12,disk=60)['ready'])
        result=self.probe(memory=11,disk=59)
        self.assertFalse(result['ready'])
        self.assertEqual(result['reasons'],['available_memory','free_disk'])

    def test_isolation_fails_closed(self):
        for args,reason in [({'quota':-1},'resource_limits'),({'own':False},'worker_outside_resource_group'),({'engine':False},'wrong_docker_engine')]:
            with self.subTest(reason=reason):
                self.assertIn(reason,self.probe(**args)['reasons'])

    def test_probe_failure_fails_closed(self):
        with patch.dict(os.environ,{'PIPELINE_RESOURCE_GATE':'true'},clear=True), \
             patch.object(resource_gate.Path,'read_text',side_effect=OSError('unavailable')):
            self.assertEqual(resource_gate.inspect()['reasons'],['resource_probe_failed'])

    def test_legacy_disabled(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(resource_gate.inspect(),{'ready':True,'enabled':False})
