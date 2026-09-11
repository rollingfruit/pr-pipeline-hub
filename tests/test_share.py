import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from publish_results import inputs
from share_viewer import ArchiveHub, ingest


class ShareTests(unittest.TestCase):
    def test_private_inputs_and_symlinks_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ['private/auth.json', 'sources/main.go', 'prepare.log', 'artifacts/report.html', 'artifacts/private/auth.json']:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture')
            (root / 'artifacts/link').symlink_to(root / 'private/auth.json')
            self.assertEqual({p.relative_to(root).as_posix() for p in inputs(root, True)}, {'prepare.log', 'artifacts/report.html'})

    def test_reject_archive_traversal(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as tar:
            info = tarfile.TarInfo('../escape')
            info.size = 1
            tar.addfile(info, io.BytesIO(b'x'))
        stream.seek(0)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                ingest(Path(temp), stream)

    def test_archive_does_not_mutate_running_result(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict('os.environ', {'PIPELINE_PUBLIC_BASE_URL': 'https://example.invalid'}):
            path = Path(temp) / 'runs/run-1'
            path.mkdir(parents=True)
            (path / 'run.json').write_text(json.dumps({'id': 'run-1', 'status': 'running'}))
            archive = ArchiveHub(Path(temp))
            self.assertEqual(archive.get_run('run-1')['status'], 'running')
            self.assertFalse(hasattr(archive, 'worker'))
            self.assertFalse(hasattr(archive, 'create_run'))


if __name__ == '__main__':
    unittest.main()
