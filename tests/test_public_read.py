import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from control_api import create_app
from share_viewer import ArchiveHub


class PublicReadTests(unittest.TestCase):
    def test_internal_archive_receipt(self):
        import io
        import hashlib
        import json
        import tarfile
        body=json.dumps({'id':'cloud-test','status':'completed'}).encode()
        manifest=json.dumps({'run_id':'cloud-test','files':{'run.json':hashlib.sha256(body).hexdigest()}}).encode()
        stream=io.BytesIO()
        with tarfile.open(fileobj=stream,mode='w:gz') as archive:
            for name,data in [('run.json',body),('manifest.json',manifest)]:
                info=tarfile.TarInfo(name);info.size=len(data);archive.addfile(info,io.BytesIO(data))
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{
            'PIPELINE_PUBLIC_READ':'true','PIPELINE_PUBLIC_BASE_URL':'https://example.invalid','PIPELINE_WORKER_TOKEN':'test-worker'}), patch('share_viewer.shutil.chown'):
            store=Mock()
            with TestClient(create_app(store,ArchiveHub(Path(folder)))) as client:
                result=client.post('/internal/artifacts',content=stream.getvalue(),headers={'X-Worker-Token':'test-worker'})
                self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(result.json()['run_id'],'cloud-test')
                self.assertEqual((Path(folder)/'runs/cloud-test/run.json').read_bytes(),body)

    def test_public_read_does_not_allow_unsigned_writes(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
            'PIPELINE_PUBLIC_READ':'true', 'PIPELINE_PUBLIC_BASE_URL':'http://example.invalid',
            'PIPELINE_WORKER_TOKEN':'worker-secret', 'PIPELINE_WEBHOOK_SECRET':'hook-secret'}):
            store=Mock()
            store.runs.return_value=[]
            store.monitors.return_value=[]
            with TestClient(create_app(store, ArchiveHub(Path(folder)))) as client:
                self.assertEqual(client.get('/api/runs').status_code,200)
                self.assertEqual(client.get('/api/monitors').status_code,200)
                self.assertEqual(client.post('/internal/claim',json={}).status_code,401)
                self.assertEqual(client.post('/internal/artifacts',content=b'not-an-archive').status_code,401)
                self.assertEqual(client.post('/internal/artifacts',content=b'not-an-archive',headers={'X-Worker-Token':'worker-secret'}).status_code,400)
                self.assertEqual(client.post('/webhooks/github',json={}).status_code,401)
                self.assertNotEqual(client.post('/api/runs',json={}).status_code,200)
                old=client.get('/reviews?access_token=obsolete&filter=recent',follow_redirects=False)
                self.assertEqual(old.status_code,303)
                self.assertNotIn('access_token',old.headers['location'])
                self.assertIn('filter=recent',old.headers['location'])
                store.claim.assert_not_called()


if __name__=='__main__':
    unittest.main()
