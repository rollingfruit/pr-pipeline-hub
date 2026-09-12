import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from gamma_rollout import GammaRollout


class RolloutTests(unittest.TestCase):
    def setUp(self):
        lease = patch('gamma_lease.check', return_value={'ok': True})
        lease.start()
        self.addCleanup(lease.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.original = {'metadata': {'uid': 'u1', 'resourceVersion': '42'}, 'spec': {'template': {
            'spec': {'containers': [{'name': 'governance', 'image': 'old-image'}]}}}}
        self.current = copy.deepcopy(self.original)
        self.commands = []
        adapter = SimpleNamespace(resolve_deploy_target=lambda *args: ('governance', 'governance'),
                                  pick_container=lambda *args, **kwargs: 'governance')
        access = SimpleNamespace(environment={'service_id': 'agent-governance-gw', 'workload_name': 'governance'},
            adapter=adapter, namespace='default', resource=lambda *args: copy.deepcopy(self.current),
            remote=lambda command, **kwargs: self.commands.append(command))
        self.manifest = {'result': {'service_id': 'agent-governance-gw', 'ok': True, 'commit_sha': 'a'*40},
            'pinned_image': 'swr.cn-southwest-2.myhuaweicloud.com/public_ai/agent-governance-gw@sha256:'+'b'*64}
        self.rollout = GammaRollout(access, self.manifest, self.directory.name)

    def test_apply_uses_uid_and_resource_version(self):
        self.rollout.prepare()
        self.rollout.apply()
        self.assertTrue(self.rollout.applied)
        self.assertIn('/metadata/uid', self.commands[0])
        self.assertIn('/metadata/resourceVersion', self.commands[0])
        self.assertIn('--timeout=240s', self.commands[1])

    def test_restore_only_our_template(self):
        self.rollout.prepare()
        self.current['spec']['template'] = copy.deepcopy(self.rollout.expected)
        self.assertEqual(self.rollout.rollback(), 'restored')
        self.assertIn('old-image', self.commands[0])

    def test_external_change_refuses_rollback(self):
        self.rollout.prepare()
        self.current['spec']['template']['spec']['containers'][0]['image'] = 'someone-elses-image'
        with self.assertRaisesRegex(RuntimeError, 'externally'):
            self.rollout.rollback()
        self.assertEqual(self.commands, [])

    def test_no_mutation_when_unchanged(self):
        self.rollout.prepare()
        self.assertEqual(self.rollout.rollback(), 'unchanged')
        self.assertEqual(self.commands, [])

    def test_reject_wrong_service(self):
        self.manifest['result']['service_id'] = 'other'
        with self.assertRaises(ValueError):
            self.rollout.prepare()

    def test_lease_loss_refuses_cluster_mutation(self):
        self.rollout.prepare()
        with patch('gamma_lease.check', side_effect=PermissionError('expired')):
            with self.assertRaises(PermissionError):
                self.rollout.apply()
        self.assertEqual(self.commands, [])


if __name__ == '__main__':
    unittest.main()
