import copy
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock
from batches import validate,resolve
from batch_runner import BatchRunner
from e2e_runner import EnvironmentFailure


def manifest():
    return {'submission_id':'test-batch-001','name':'test','members':[{'repo':'rollingfruit/agent-governance-gw','repo_id':1,'pr_number':1,'pr_url':'https://github.com/rollingfruit/agent-governance-gw/pull/1','head_sha':'a'*40,'base_sha':'b'*40}],
            'suite_ids':['E01','E02','E03'],'baseline_enabled':True,'codex_review':False,'github_write':True}


class BatchTests(unittest.TestCase):
    def test_core_and_partial(self):
        b=manifest();self.assertTrue(validate(b)[1]);b['baseline_enabled']=False;self.assertFalse(validate(b)[1])
        b['suite_ids']=['E02'];self.assertFalse(validate(b)[1])
    def test_invalid_selection(self):
        for update in [{'members':[]},{'suite_ids':[]},{'suite_ids':['E04']},{'codex_review':'false'}]:
            with self.assertRaises(ValueError):validate({**manifest(),**update})
        b=manifest();b['members']*=2
        with self.assertRaises(ValueError):validate(b)
    def test_unsupported_and_bad_url(self):
        result=resolve(Mock(),['bad','https://github.com/rollingfruit/public-service/pull/1'])
        self.assertEqual([r['code'] for r in result],['invalid_link','unsupported'])
    def test_disabled_review_does_not_call_model(self):
        r=BatchRunner.__new__(BatchRunner);r.run={'options':{'codex_review':False}};r.agent_review()
        self.assertEqual(r.run['review']['status'],'disabled')
    def test_optional_review_preserves_batch_selection(self):
        from local_agent_review import review
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ',{'PIPELINE_CODEX_HOME':directory}):
            root=Path(directory);(root/'auth.json').write_text('{}')
            runner=Mock();runner.folder=root;runner.artifacts=root
            runner.run={'kind':'batch','repo':'rollingfruit/agent-governance-gw','head_sha':'a'*40,'base_sha':'b'*40,
                        'suites':[{'id':'E02'}],'stages':[{'id':'agent'}]}
            original=copy.deepcopy(runner.run)
            runner.stack.config.return_value={'CODEX_HOME':directory,'CODEX_MODEL':'test-model'}
            def execute(argv,**kwargs):
                Path(argv[argv.index('-o')+1]).write_text(json.dumps({'summary':'unit test','findings':[],'additional_suites':['DR']}))
            runner.command.side_effect=execute
            result=review(runner,{'repo':'rollingfruit/semantic-schedule','workspace':directory})
            self.assertEqual(runner.run,original)
            self.assertEqual(result['additional_suites'],['DR'])
            runner.hub._prepare.assert_not_called()
    def test_version_mismatch_has_evidence(self):
        r=BatchRunner.__new__(BatchRunner);r.run={'members':manifest()['members']};r.save=Mock()
        r.hub=Mock();r.hub._gh_json.side_effect=[{'state':'open','head':{'sha':'a'*40},'base':{'ref':'main'}},{'object':{'sha':'c'*40}}]
        with self.assertRaises(EnvironmentFailure):r.verify_versions()
        self.assertTrue(r.run['stale']);self.assertEqual(r.run['version_checks'][0]['actual_base'],'c'*40)


if __name__=='__main__':unittest.main()
