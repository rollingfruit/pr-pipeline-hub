"""Opt-in tests use a disposable schema, never the production queue tables."""
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor


@unittest.skipUnless(os.getenv('GAMMA_TEST_DSN'), 'Disposable PostgreSQL schema needs GAMMA_TEST_DSN')
class PostgresQueueTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg.conninfo import make_conninfo
        from control_store import Store
        self.schema = 'gamma_test_' + uuid.uuid4().hex
        with psycopg.connect(os.environ['GAMMA_TEST_DSN']) as db:
            db.execute('CREATE SCHEMA ' + self.schema)
        self.store = Store(make_conninfo(os.environ['GAMMA_TEST_DSN'], options='-c search_path=' + self.schema))
        self.store.initialize()

    def tearDown(self):
        import psycopg
        with psycopg.connect(os.environ['GAMMA_TEST_DSN']) as db:
            db.execute('DROP SCHEMA ' + self.schema + ' CASCADE')

    def submit(self, name):
        from gamma_queue import submit
        return submit(self.store, {'submission_id': name, 'environment_id': 'env', 'suite_ids': ['E01']})

    def test_fifo_single_claim_and_idempotency(self):
        first = self.submit('first')
        self.assertEqual(self.submit('first')['id'], first['id'])
        second = self.submit('second')
        with ThreadPoolExecutor(2) as pool:
            claims = list(pool.map(lambda _: self.store.claim('test', []), range(2)))
        claim = next(c for c in claims if c)
        self.assertEqual(sum(c is not None for c in claims), 1)
        self.assertEqual(claim['run']['id'], first['id'])
        self.store.update(first['id'], claim['lease_token'], {'status': 'completed',
                          'cleanup': {'status': 'passed', 'active_residuals': []}, 'environment_health': 'ready'}, final=True)
        self.assertEqual(self.store.claim('test', [])['run']['id'], second['id'])

    def test_expired_claim_blocks_takeover_and_old_write(self):
        self.submit('first')
        self.submit('second')
        claim = self.store.claim('test', [])
        with self.store.db() as db:
            db.execute("UPDATE reviews SET lease_until=now()-interval '1 second' WHERE id=%s", (claim['run']['id'],))
        self.assertIsNone(self.store.claim('replacement', []))
        with self.assertRaises(PermissionError):
            self.store.update(claim['run']['id'], claim['lease_token'], {'status': 'completed'}, final=True)

    def test_cleanup_failure_quarantines_queue(self):
        self.submit('first')
        self.submit('second')
        claim = self.store.claim('test', [])
        self.store.update(claim['run']['id'], claim['lease_token'], {'status': 'completed',
                          'cleanup': {'status': 'failed'}, 'environment_health': 'ready'}, final=True)
        self.assertIsNone(self.store.claim('test', []))
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT state FROM execution_environments').fetchone()['state'], 'quarantined')

    def test_recovery_requires_remote_and_cleanup_evidence(self):
        first = self.submit('first')
        second = self.submit('second')
        claim = self.store.claim('first-worker', [])
        self.store.update(first['id'], claim['lease_token'], {'status': 'completed',
                          'cleanup': {'status': 'failed'}, 'environment_health': 'ready'}, final=True)
        evidence = {'environment_unlocked': True, 'processes_reconciled': True}
        with self.assertRaises(ValueError):
            self.store.recover(first['id'], evidence)
        self.assertIsNone(self.store.claim('replacement-worker', []))
        evidence.update(cleanup={'status': 'passed', 'active_residuals': []}, environment_health='ready',
                        archive_verified=True, remote_operations_reconciled=True)
        self.store.recover(first['id'], evidence)
        self.assertEqual(self.store.claim('replacement-worker', [])['run']['id'], second['id'])
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) AS n FROM deliveries').fetchone()['n'], 0)
