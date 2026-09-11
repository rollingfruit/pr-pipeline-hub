"""Database contract tests; uses an isolated schema, never production review rows."""
import copy
import hashlib
import json
import os
import secrets
import unittest
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row
from control_store import Store
from review_policy import select


class PolicyTests(unittest.TestCase):
    def test_unknown_paths_keep_core(self):
        self.assertEqual([s['id'] for s in select('rollingfruit/other', ['README.md'])['suites']], ['E01','E02','E03'])

    def test_direct_answer_without_pr_number(self):
        self.assertEqual(len(select('rollingfruit/agent-governance-gw', ['internal/directreply/handler.go'])['suites']), 5)

    def test_risky_and_agent_cannot_remove(self):
        policy = select('rollingfruit/multica-aiwelink', ['build/package/build.sh'], ['DR'])
        self.assertEqual(len(policy['risky_files']), 1)
        self.assertEqual(len(policy['suites']), 4)
        with self.assertRaises(ValueError):
            select('r', [], ['E06'])


@unittest.skipUnless(os.getenv('PIPELINE_DATABASE_URL'), 'PostgreSQL DSN required')
class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.dsn = os.environ['PIPELINE_DATABASE_URL']
        self.schema = 'test_' + secrets.token_hex(8)
        with psycopg.connect(self.dsn) as db:
            db.execute(f'CREATE SCHEMA {self.schema}')
        self.store = Store(self.dsn)
        self.store.db = lambda: psycopg.connect(self.dsn, row_factory=dict_row, options=f'-c search_path={self.schema}')
        self.store.initialize()
        self.store.register(12, 'rollingfruit/test')
        self.tick = datetime.now(timezone.utc) + timedelta(seconds=2)

    def tearDown(self):
        with psycopg.connect(self.dsn) as db:
            db.execute(f'DROP SCHEMA {self.schema} CASCADE')

    def event(self, number=1, head='a'*40, action='opened', **changes):
        self.tick += timedelta(seconds=1)
        payload = {'repository': {'id':12}, 'action':action, 'pull_request':{
            'number':number, 'title':'test', 'html_url':f'https://github.com/rollingfruit/test/pull/{number}',
            'updated_at': self.tick.isoformat(), 'head':{'sha':head,'ref':'feature'},
            'base':{'sha':'b'*40,'ref':'main'}, **changes}}
        return payload

    def send(self, payload, delivery=None, event='pull_request'):
        return self.store.receive(delivery or secrets.token_hex(8), hashlib.sha256(json.dumps(payload).encode()).hexdigest(), event, payload)

    def test_duplicate_and_out_of_order(self):
        p = self.event()
        first = self.send(p, 'delivery')
        self.assertTrue(self.send(p, 'delivery')['duplicate'])
        newer = self.event(head='c'*40, action='synchronize')
        self.send(newer)
        self.assertEqual(self.send(p)['ignored'], 'out of order')
        self.assertEqual(len(self.store.runs()), 2)
        self.assertEqual(next(r for r in self.store.runs() if r['id']==first['id'])['status'], 'superseded')

    def test_fifo_fencing_and_expiration(self):
        first = self.send(self.event())['id']
        self.send(self.event(2))
        claimed = self.store.claim('one')
        self.assertEqual(claimed['run']['id'], first)
        self.assertIsNone(self.store.claim('two'))
        with self.assertRaises(PermissionError):
            self.store.update(first, 'wrong', {})
        with self.store.db() as db:
            db.execute("UPDATE reviews SET lease_until=now()-interval '1 second' WHERE id=%s", (first,))
        with self.assertRaises(PermissionError):
            self.store.update(first, claimed['lease_token'], {})
        self.assertIsNone(self.store.claim('two'))
        self.assertEqual(next(r for r in self.store.runs() if r['id']==first)['status'], 'interrupted')

    def test_close_draft_and_rename(self):
        self.send(self.event(draft=True))
        self.assertIsNone(self.store.claim('one'))
        self.send(self.event(action='ready_for_review', draft=False))
        self.store.register(12, 'rollingfruit/renamed')
        self.assertEqual(len(self.store.repositories()), 1)
        close = self.event(action='closed')
        self.send(close)
        self.assertIsNone(self.store.claim('one'))
        self.assertEqual(self.store.runs()[0]['pr_state'], 'CLOSED')

    def test_old_running_and_target_branch_change(self):
        first = self.send(self.event())['id']
        claim = self.store.claim('one')
        self.send(self.event(head='c'*40, action='synchronize'))
        self.assertTrue(self.store.update(first, claim['lease_token'], {'stale':False})['stale'])
        self.send({'repository':{'id':12}, 'ref':'refs/heads/main'}, event='push')
        self.assertTrue(all(r['stale'] for r in self.store.runs()))

    def test_unregistered_and_payload_reuse(self):
        p = self.event()
        self.send(p, 'same')
        with self.assertRaises(ValueError):
            self.send(self.event(2), 'same')
        p['repository']['id'] = 99
        with self.assertRaises(PermissionError):
            self.send(p)

    def test_close_before_open_and_delivery_receipt(self):
        opening = self.event()
        self.send(self.event(action='closed'))
        self.assertEqual(self.send(opening)['ignored'], 'out of order')
        self.assertEqual(self.store.runs(), [])
        self.send(self.event(action='reopened'))
        delivery = self.store.claim_delivery()
        with self.assertRaises(ValueError):
            self.store.finish_delivery(delivery['id'], delivery['attempts'], {'ok':True})
        self.store.finish_delivery(delivery['id'], delivery['attempts'], {'ok':False,'error':'test offline'})
        self.assertFalse(self.store.runs()[0]['deliveries'][0]['ok'])

    def test_http_signature_and_read_authorization(self):
        import hmac
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from control_api import create_app
        from share_viewer import ArchiveHub
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
            'PIPELINE_PUBLIC_BASE_URL':'http://example.invalid', 'PIPELINE_VIEW_TOKEN':'test-view',
            'PIPELINE_WORKER_TOKEN':'test-worker', 'PIPELINE_WEBHOOK_SECRET':'test-secret'}):
            app = create_app(self.store, ArchiveHub(Path(folder)))
            with TestClient(app) as client:
                self.assertEqual(client.get('/api/runs').status_code, 401)
                self.assertEqual(client.post('/internal/claim', json={}).status_code, 401)
                body = json.dumps(self.event()).encode()
                headers = {'x-github-event':'pull_request','x-github-delivery':'test',
                           'x-hub-signature-256':'sha256='+hmac.new(b'test-secret',body,hashlib.sha256).hexdigest()}
                self.assertEqual(client.post('/webhooks/github',content=body).status_code,401)
                self.assertEqual(client.post('/webhooks/github',content=body,headers=headers).status_code,200)
                self.assertTrue(client.post('/webhooks/github',content=body,headers=headers).json()['duplicate'])
                self.assertEqual(client.post('/webhooks/github',content=b'x'*(2*1024*1024+1)).status_code,413)
                response = client.get('/?access_token=test-view', follow_redirects=False)
                self.assertEqual(response.status_code,303)
                self.assertIn('HttpOnly',response.headers['set-cookie'])
                self.assertEqual(len(client.get('/api/runs').json()['runs']),1)

    def test_poll_and_webhook_share_one_review(self):
        event=self.event()
        digest=hashlib.sha256(json.dumps(event).encode()).hexdigest()
        first=self.store.receive('poll-test',digest,'pull_request',event,'github_poll')
        second=self.send(event,'hook-test')
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(len(self.store.runs()),1)
        self.assertEqual(self.store.runs()[0]['trigger_source'],'github_poll')
        self.store.set_monitor('test',{'status':'watching','latest':{'number':1}})
        self.assertEqual(self.store.monitors()[0]['latest']['number'],1)

    def test_explicit_retry_keeps_old_evidence_and_delivery_receipt(self):
        event = self.event()
        first = self.send(event, 'original-event')
        claim = self.store.claim('worker')
        self.store.update(first['id'], claim['lease_token'], {'status':'completed', 'failure_kind':'error'}, True)
        retry = copy.deepcopy(event)
        retry['manual_retry'] = True
        retry['pull_request']['updated_at'] = (self.tick + timedelta(seconds=2)).isoformat()
        second = self.store.receive('retry-event', 'retry-digest', 'pull_request', retry, 'local_manual')
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(self.store.runs(second['id'])[0]['retry_of'], first['id'])
        self.assertEqual(self.send(event, 'original-event')['id'], first['id'])
        self.assertEqual(self.store.runs(first['id'])[0]['status'], 'completed')
        third = copy.deepcopy(retry)
        with self.assertRaises(ValueError):
            self.store.receive('illegal-retry', 'another-digest', 'pull_request', third, 'local_manual')


if __name__ == '__main__':
    unittest.main()
