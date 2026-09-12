import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

root = Path(os.environ.get('PIPELINE_E2E_ROOT', Path(__file__).resolve().parents[2] /
                         'mattermost-microservice/infra/pr-e2e'))
spec = importlib.util.spec_from_file_location('frozen_settings_stack', root / 'stack.py')
stack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stack)


class FrozenSettingsTests(unittest.TestCase):
    def test_runtime_reconnection_does_not_rewrite_frozen_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'frozen.json'
            original = {'DAEMON_ID': 'owned', 'RUNTIME_ID': 'runtime', 'OPENCODE_MODEL': 'fixed'}
            path.write_text(json.dumps(original))
            with patch.dict(os.environ, E2E_FROZEN_SETTINGS=str(path)):
                stack.output_json(path, {**original, 'RUNTIME_ID': ''})
                self.assertEqual(json.loads(path.read_text()), original)
                with self.assertRaises(RuntimeError):
                    stack.output_json(path, {**original, 'OPENCODE_MODEL': 'other'})
                with self.assertRaises(RuntimeError):
                    stack.output_json(path, {**original, 'DAEMON_ID': 'other'})
