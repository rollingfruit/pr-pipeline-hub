import io
import json
import os
import unittest
from unittest.mock import patch, MagicMock
import urllib.error
import robot_session


class SessionTests(unittest.TestCase):
    def check(self, payload):
        opener = MagicMock()
        opener.open.return_value = io.BytesIO(json.dumps(payload).encode())
        with patch('urllib.request.build_opener', return_value=opener):
            return robot_session.check('session=test')

    def test_valid_user(self):
        self.assertEqual(self.check({'user': 'operator'}), 'operator')

    def test_anonymous_200_is_denied(self):
        for payload in ({'user': None}, {}, {'user': {}}, {'user': True}, {'user': ' '}):
            self.assertEqual(self.check(payload), '')

    def test_legacy_url_uses_existing_contract(self):
        with patch.dict(os.environ, {'PIPELINE_ROBOT_AUTH_URL': 'http://127.0.0.1:18082/api/auth/pipeline'}):
            opener = MagicMock()
            opener.open.return_value = io.BytesIO(b'{"user":"operator"}')
            with patch('urllib.request.build_opener', return_value=opener):
                self.assertEqual(robot_session.check('secret'), 'operator')
            self.assertEqual(opener.open.call_args.args[0].full_url, 'http://127.0.0.1:18082/api/auth/me')

    def test_backend_failure(self):
        opener = MagicMock()
        opener.open.side_effect = urllib.error.HTTPError('url', 404, 'missing', {}, None)
        with patch('urllib.request.build_opener', return_value=opener):
            with self.assertRaises(robot_session.Unavailable):
                robot_session.check('secret')
            self.assertEqual(robot_session.username('secret'), '')

    def test_remote_backend_rejected(self):
        with patch.dict(os.environ, {'PIPELINE_ROBOT_AUTH_URL': 'http://example.com/api/auth/me'}):
            with self.assertRaises(robot_session.Unavailable):
                robot_session.check('secret')


if __name__ == '__main__':
    unittest.main()
