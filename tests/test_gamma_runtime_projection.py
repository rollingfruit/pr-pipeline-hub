import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

STACK = Path(os.environ.get('PIPELINE_E2E_ROOT', Path(__file__).resolve().parents[2] /
                         'mattermost-microservice/infra/pr-e2e'))
sys.path.insert(0, str(STACK))
spec = importlib.util.spec_from_file_location('gamma_bootstrap_test', STACK / 'bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
import local_daemon


class RuntimeProjectionTests(unittest.TestCase):
    def ready(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'internal.json').write_text('{"token":"fixture-only"}')
            with patch.dict(os.environ, {'E2E_PRIVATE_DIR': directory}), patch.object(
                bootstrap, 'urlopen', return_value=io.BytesIO(json.dumps({'runtimes': rows}).encode())):
                return bootstrap.ready_runtime_ids({'WORKSPACE_ID': 'workspace', 'DAEMON_ID': 'daemon'},
                                                   {'id': 'test-user'}, 'opencode')

    def row(self, **changes):
        return {'id': 'runtime', 'workspace_id': 'workspace', 'daemon_id': 'daemon',
                'provider': 'opencode', 'status': 'online', 'publishable_for_current_user': True,
                'metadata': {'version': '1.18.30', 'provider_ready': True}, **changes}

    def test_raw_provider_evidence(self):
        self.assertEqual(self.ready([self.row()]), {'runtime'})

    def test_no_ready_flag_or_version_is_not_ready(self):
        for metadata in (None, {}, {'version':'1.18.30'}, {'provider_ready': True}):
            self.assertEqual(self.ready([self.row(metadata=metadata)]), set())

    def test_foreign_identity_or_offline_is_not_ready(self):
        for changes in ({'daemon_id':'another'}, {'workspace_id':'another'}, {'status':'offline'},
                        {'provider':'codex'}, {'publishable_for_current_user':False}):
            self.assertEqual(self.ready([self.row(**changes)]), set())

    def test_string_metadata_contract(self):
        self.assertEqual(self.ready([self.row(metadata=json.dumps({'version':'1.18.30','provider_ready':True}))]), {'runtime'})

    def test_fixture_permission_is_narrow_and_does_not_modify_shared_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / 'workspace'
            fixture.mkdir()
            config = root / 'shared.json'
            original = {'permission': {'read': 'allow', 'external_directory': {'*': 'deny', '/old': 'allow'}}}
            config.write_text(json.dumps(original))
            with patch.object(local_daemon, 'STATE', root / 'state'):
                output = local_daemon.configure_fixture_access(root, config, fixture)
            actual = json.loads(Path(output).read_text())
            self.assertEqual(actual['permission']['external_directory'], {
                '*': 'deny', str(fixture.resolve()): 'allow', str(fixture.resolve()) + '/**': 'allow'})
            self.assertEqual(json.loads(config.read_text()), original)
            self.assertEqual(actual['permission']['read'], 'allow')

    def test_fixture_cannot_authorize_execution_root_or_external_directory(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as external:
            root = Path(directory)
            with patch.object(local_daemon, 'STATE', root / 'state'):
                for target in (root, Path(external)):
                    with self.assertRaises(RuntimeError):
                        local_daemon.configure_fixture_access(root, root / 'unused.json', target)


if __name__ == '__main__':
    unittest.main()
