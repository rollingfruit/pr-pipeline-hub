import copy
import os
import secrets
from datetime import datetime,timezone,timedelta
import unittest
import psycopg
from psycopg.rows import dict_row
from batch_store import create
from control_store import Store


class BatchDatabaseTests(unittest.TestCase):
    def test_shared_queue_and_idempotency(self):
        dsn=os.environ['PIPELINE_DATABASE_URL'];schema='batchtest_'+secrets.token_hex(8)
        with psycopg.connect(dsn) as db:db.execute('CREATE SCHEMA '+schema)
        try:
            store=Store(dsn);store.db=lambda:psycopg.connect(dsn,row_factory=dict_row,options='-c search_path='+schema)
            store.initialize();store.register(1,'rollingfruit/agent-governance-gw');store.register(2,'rollingfruit/multica-aiwelink')
            members=[{'repo':repo,'repo_id':i,'pr_number':1,'pr_url':f'https://github.com/{repo}/pull/1','head_sha':'a'*40,'base_sha':'b'*40} for i,repo in [(1,'rollingfruit/agent-governance-gw'),(2,'rollingfruit/multica-aiwelink')]]
            body={'name':'test','submission_id':'isolated-test-001','members':members,'suite_ids':['E01','E02','E03'],'codex_review':False,'baseline_enabled':True,'github_write':True,'baseline_revisions':{}}
            result=create(store,body);self.assertTrue(create(store,body)['duplicate'])
            with self.assertRaises(ValueError):create(store,{**body,'name':'changed'})
            second=create(store,{**body,'submission_id':'isolated-test-002'})
            claim=store.claim('test',[]);self.assertEqual(claim['run']['id'],result['id']);self.assertIsNone(store.claim('other',[]))
            with self.assertRaises(PermissionError):store.update(result['id'],'wrong',{},True)
            store.update(result['id'],claim['lease_token'],{'status':'completed','conclusion':'success'},True)
            self.assertEqual(store.claim('next',[])['run']['id'],second['id'])
            row=store.runs(result['id'])[0];self.assertEqual(len(row['deliveries']),6)
            pending=store.claim_delivery()
            store.finish_delivery(pending['id'],pending['attempts'],{'ok':False,'error':'network unavailable'})
            with store.db() as db:
                db.execute("UPDATE deliveries SET next_attempt=now() WHERE id=%s",(pending['id'],))
            retry=store.claim_delivery();self.assertEqual(retry['id'],pending['id'])
            self.assertGreater(retry['attempts'],pending['attempts'])
            with self.assertRaises(PermissionError):store.finish_delivery(pending['id'],pending['attempts'],{'ok':False})
            event={'repository':{'id':2},'action':'synchronize','pull_request':{'number':1,'updated_at':(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat(),'head':{'sha':'c'*40}}}
            self.assertTrue(store.receive('new-head','digest','pull_request',event)['discovery_only'])
            self.assertTrue(store.runs(second['id'])[0]['stale'])
            with store.db() as db:db.execute("UPDATE reviews SET lease_until=now()-interval '1 second' WHERE id=%s",(second['id'],))
            self.assertIsNone(store.claim('expired',[]))
            self.assertEqual(store.runs(second['id'])[0]['status'],'interrupted')
            store.recover(second['id'],{'environment_unlocked':True,'processes_reconciled':True})
            recovered=store.runs(second['id'])[0]
            self.assertEqual(recovered['status'],'blocked')
            self.assertEqual({d['channel'] for d in recovered['deliveries'] if d['phase']=='final'},
                             {'batch_status:1','batch_status:2','batch_comment:1','batch_comment:2'})
        finally:
            with psycopg.connect(dsn) as db:db.execute('DROP SCHEMA '+schema+' CASCADE')


if __name__=='__main__':unittest.main()
