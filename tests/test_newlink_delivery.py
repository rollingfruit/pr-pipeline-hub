import unittest
from unittest.mock import Mock
from newlink_delivery import payload, receipt, GROUP, ACCOUNT


class NewLinkTests(unittest.TestCase):
    def test_real_receipt_required(self):
        for value in ({'code':0},{'code':401,'imMsgId':'x'},{'code':False,'imMsgId':'x'}):
            with self.assertRaises(RuntimeError):
                receipt(value)
        actual=receipt({'code':2602,'imMsgId':'real-message'})
        self.assertEqual(actual['receipt_id'],'real-message')
        self.assertEqual(actual['agent_execution'],'not_requested')

    def test_no_fake_source_or_historical_flood(self):
        config={'enabled_after':'2026-09-09T00:00:00Z','agent_account':ACCOUNT,'group_id':GROUP,'tenant_id':'test','corp_id':1}
        hub=Mock()
        hub._run_web_url.return_value='http://119.8.233.58:8080/runs/test'
        item={'phase':'final','run':{'id':'test','created_at':'2026-09-09T01:00:00Z','pr_number':96,
            'pr_url':'https://github.com/rollingfruit/agent-governance-gw/pull/96'}}
        first=payload(hub,item,config)
        self.assertEqual(first['sourceMsgId'],'')
        self.assertEqual(first['replyToMsgId'],'')
        self.assertEqual(first['requestId'],payload(hub,item,config)['requestId'])
        config['enabled_after']='2026-09-10T00:00:00Z'
        with self.assertRaises(ValueError):
            payload(hub,item,config)
