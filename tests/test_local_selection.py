import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer
from local_selection import Handler, TOKEN
from local_agent_review import validate_review


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, headers):
        client = http.client.HTTPConnection(*self.server.server_address)
        client.request(method, '/api/enqueue' if method=='POST' else '/', body='{}' if method=='POST' else None, headers=headers)
        response = client.getresponse()
        status, body = response.status, response.read()
        client.close()
        return status, body

    def test_rebinding_and_unauthorized_writes_rejected(self):
        self.assertEqual(self.request('GET', {'Host':'attacker.invalid'})[0], 403)
        self.assertEqual(self.request('POST', {'Host':'127.0.0.1:8793'})[0], 403)
        self.assertEqual(self.request('POST', {'Host':'127.0.0.1:8793','X-Selection-Token':TOKEN,'Origin':'https://attacker.invalid'})[0], 403)

    def test_local_page_has_actual_queue_control(self):
        status, body = self.request('GET', {'Host':'127.0.0.1:8793'})
        self.assertEqual(status, 200)
        self.assertIn(b'/api/enqueue', body)

    def test_review_cannot_fake_coverage(self):
        valid = {'summary':'reviewed', 'findings':[], 'additional_suites':['DR']}
        self.assertEqual(validate_review(valid), valid)
        for patch in ({'summary':''}, {'additional_suites':['E06']}, {'findings':[{'severity':'okay'}]}):
            with self.assertRaises(ValueError):
                validate_review({**valid, **patch})
