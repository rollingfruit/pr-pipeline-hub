import os
import secrets
import unittest
import psycopg
from psycopg.rows import dict_row
from artifact_batches import create
from control_store import Store
from test_artifact_batches import manifest


@unittest.skipUnless(os.getenv('PIPELINE_DATABASE_URL'),'requires isolated PostgreSQL schema')
class ArtifactDatabaseTests(unittest.TestCase):
    def test_single_queue_and_no_deliveries(self):
        dsn=os.environ['PIPELINE_DATABASE_URL'];schema='artifacttest_'+secrets.token_hex(8)
        with psycopg.connect(dsn) as db:db.execute('CREATE SCHEMA '+schema)
        try:
            store=Store(dsn);store.db=lambda:psycopg.connect(dsn,row_factory=dict_row,options='-c search_path='+schema)
            store.initialize();store.register(1,'rollingfruit/agent-governance-gw')
            body=manifest();first=create(store,body)
            self.assertTrue(create(store,body)['duplicate'])
            with self.assertRaises(ValueError):create(store,{**body,'baseline_enabled':False})
            second=create(store,{**body,'build_id':'test-456'})
            claim=store.claim('test',[]);self.assertEqual(claim['run']['id'],first['id'])
            self.assertIsNone(store.claim('another',[]))
            with self.assertRaises(PermissionError):store.update(first['id'],'wrong',{},True)
            store.update(first['id'],claim['lease_token'],{'status':'completed','conclusion':'failure'},True)
            self.assertEqual(store.claim('test',[])['run']['id'],second['id'])
            self.assertEqual(store.runs(first['id'])[0]['deliveries'],[])
        finally:
            with psycopg.connect(dsn) as db:db.execute('DROP SCHEMA '+schema+' CASCADE')

if __name__=='__main__':unittest.main()
