import unittest
from unittest.mock import Mock, patch
import github_deliveries


class DeliveryTests(unittest.TestCase):
    def test_newlink_requires_real_provider(self):
        with self.assertRaisesRegex(RuntimeError, 'not configured'):
            github_deliveries.send(Mock(), {'run':{'repo':'owner/repo'},'channel':'newlink'})

    def test_ambiguous_status_is_reconciled(self):
        hub = Mock(public_base_url='http://example.invalid')
        hub._gh_json.return_value = [{'id':10,'context':'newlink/e2e-local','state':'error',
                                    'description':'E2E error; run test'}]
        receipt = github_deliveries.send(hub, {'run':{'id':'test','repo':'owner/repo','head_sha':'a'*40,
            'status':'completed','stale':True,'conclusion':'success'},'channel':'github_status','phase':'final'})
        self.assertEqual(receipt['receipt_id'], '10')
        self.assertEqual(hub._gh_json.call_count,1)

    def test_lease_loss_suppresses_status_write(self):
        from e2e_runner import E2ERunner
        runner = object.__new__(E2ERunner)
        runner.run = {'controlled':True,'_lease_lost':True}
        runner.hub = Mock()
        runner.save = Mock()
        runner.publish('success')
        runner.hub._gh_json.assert_not_called()
        self.assertFalse(runner.run['github']['ok'])


if __name__ == '__main__':
    unittest.main()
