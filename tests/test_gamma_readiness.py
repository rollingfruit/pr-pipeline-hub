import copy
import unittest
from gamma_readiness import deployment_evidence


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.deployment = {'metadata': {'name': 'multica-server', 'uid': 'dep', 'generation': 2},
            'spec': {'replicas': 1, 'template': {'spec': {'containers': [{'name': 'server', 'image': 'image@sha256:new'}]}}},
            'status': {'observedGeneration': 2, 'replicas': 1, 'updatedReplicas': 1, 'readyReplicas': 1, 'availableReplicas': 1}}
        self.rs = [{'metadata': {'uid': 'rs', 'ownerReferences': [{'uid': 'dep'}]}}]
        self.pods = [{'metadata': {'name': 'pod', 'ownerReferences': [{'uid': 'rs'}]},
            'spec': {'containers': copy.deepcopy(self.deployment['spec']['template']['spec']['containers'])},
            'status': {'containerStatuses': [{'name': 'server', 'ready': True, 'imageID': 'repo@sha256:new'}]}}]

    def test_records_real_pod_image(self):
        evidence = deployment_evidence(self.deployment, self.pods, self.rs)
        self.assertEqual(evidence['pods'][0]['containers'][0]['image_id'], 'repo@sha256:new')

    def test_old_available_replica_does_not_prove_rollout(self):
        self.deployment['status']['updatedReplicas'] = 0
        with self.assertRaisesRegex(RuntimeError, 'rollout incomplete'):
            deployment_evidence(self.deployment, self.pods, self.rs)

    def test_mismatched_pod_image_is_blocked(self):
        self.pods[0]['spec']['containers'][0]['image'] = 'old'
        with self.assertRaisesRegex(RuntimeError, 'pod image'):
            deployment_evidence(self.deployment, self.pods, self.rs)

    def test_missing_digest_is_blocked(self):
        self.pods[0]['status']['containerStatuses'][0]['imageID'] = ''
        with self.assertRaises(RuntimeError):
            deployment_evidence(self.deployment, self.pods, self.rs)
