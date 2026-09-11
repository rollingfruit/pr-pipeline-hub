import unittest
from unittest.mock import patch
import branch_batches
from batches import validate


class Hub:
    def _gh_json(self,args):
        path=args[1]
        if '/compare/' in path:return {'files':[]}
        if '/git/ref/' in path:return {'object':{'sha':('a' if path.endswith('/main') else 'b')*40}}
        if '/branches?' in path:return [[{'name':'main','commit':{'sha':'a'*40}}]]
        return {'id':1,'default_branch':'main'}


class BranchTests(unittest.TestCase):
    def test_branch_resolution_without_pr(self):
        result=branch_batches.resolve(Hub(),[{'repo':'rollingfruit/agent-governance-gw','head_ref':'feature/a'}])[0]
        self.assertTrue(result['ok']);self.assertIsNone(result['member']['pr_number'])
        self.assertEqual(result['member']['head_sha'],'b'*40)
        self.assertEqual(result['member']['base_ref'],'main')

    def test_duplicates_and_unsupported(self):
        m={'repo':'rollingfruit/agent-governance-gw','head_ref':'main'}
        self.assertFalse(branch_batches.resolve(Hub(),[m,m])[1]['ok'])
        self.assertFalse(branch_batches.resolve(Hub(),[{'repo':'rollingfruit/public-service','head_ref':'main'}])[0]['ok'])

    def test_validation_no_pr_and_nonempty_suites(self):
        m=branch_batches.resolve(Hub(),[{'repo':'rollingfruit/agent-governance-gw','head_ref':'main'}])[0]['member']
        body={'name':'branch test','source_mode':'branch','submission_id':'branch-12345678','members':[m],
              'suite_ids':['E01','E02','E03'],'baseline_enabled':True,'github_write':False,'codex_review':False}
        validate(body)
        with self.assertRaises(ValueError):validate({**body,'suite_ids':[]})
        with self.assertRaises(ValueError):validate({**body,'github_write':True})

    def test_session_failure_closed(self):
        import robot_session
        with patch.object(robot_session, 'check', side_effect=robot_session.Unavailable('offline')):
            self.assertEqual(robot_session.username('forged'),'')

    def test_version_change_marks_stale(self):
        from batch_runner import BatchRunner
        from e2e_runner import EnvironmentFailure
        runner=object.__new__(BatchRunner)
        runner.hub=Hub();runner.save=lambda:None
        member=branch_batches.resolve(runner.hub,[{'repo':'rollingfruit/agent-governance-gw','head_ref':'main'}])[0]['member']
        runner.run={'source_mode':'branch','members':[member]}
        runner.verify_versions()
        member['head_sha']='c'*40
        with self.assertRaises(EnvironmentFailure):runner.verify_versions()
        self.assertTrue(runner.run['stale'])

if __name__=='__main__':unittest.main()
