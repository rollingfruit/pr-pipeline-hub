import base64
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

from cloud_config import load, activate, enabled
from cloud_prepare import release_files, initialize
from local_selection import Handler, ThreadingHTTPServer, TOKEN

ROOT=Path(__file__).resolve().parents[1]


class CloudTests(unittest.TestCase):
    def config(self):
        return load(ROOT/'deploy/cloud/config.example.toml')

    def test_offline_config_no_secrets_needed(self):
        cfg=self.config()
        with patch.dict(os.environ,clear=True):
            activate(cfg,'model')
            self.assertFalse(enabled('github_write'))
            self.assertFalse(enabled('code_review'))
            self.assertEqual(os.environ['PIPELINE_GIT_PROXY'],'')
            self.assertNotIn('GH_TOKEN',os.environ)
            self.assertEqual(os.environ['PIPELINE_EDITOR_URL'],'https://pipeline.example.com/submit/')

    def test_check_files_checks_core_secrets(self):
        with self.assertRaises(ValueError):
            load(ROOT/'deploy/cloud/config.example.toml','check',True)

    def test_cce_manifest_structure(self):
        import yaml
        objects=list(yaml.safe_load_all((ROOT/'deploy/cloud/cce-control.yaml').read_text()))
        deploy=next(o for o in objects if o['kind']=='Deployment')
        self.assertEqual(deploy['spec']['replicas'],1)
        self.assertEqual(deploy['spec']['strategy']['type'],'Recreate')
        self.assertFalse(deploy['spec']['template']['spec']['automountServiceAccountToken'])
        service=next(o for o in objects if o['kind']=='Service')
        self.assertEqual(service['spec']['type'],'ClusterIP')

    def test_bad_configs(self):
        source=(ROOT/'deploy/cloud/config.example.toml').read_text()
        mutations=[('version = 1','version = 2'),('code_review = false','code_review = "false"'),
                   ('newlink = false','newlink = true'),('https://pipeline.example.com','http://pipeline.example.com'),
                   ('https://pipeline.example.com','https://pipeline.example.com/submit'),
                   ('https://pipeline.example.com','https://pipeline.example.com/#bad')]
        with tempfile.TemporaryDirectory() as directory:
            for old,new in mutations:
                p=Path(directory)/'config.toml';p.write_text(source.replace(old,new))
                with self.subTest(new=new),self.assertRaises(ValueError):load(p)

    def test_optional_features_cannot_be_forced(self):
        from batches import validate
        from test_batches import manifest
        with patch.dict(os.environ,{'PIPELINE_CLOUD_PROFILE':'1','PIPELINE_FEATURE_CODE_REVIEW':'false','PIPELINE_FEATURE_GITHUB_WRITE':'false'}):
            value=manifest();value['github_write']=False
            validate(value)
            for key in ('codex_review','github_write'):
                with self.subTest(key=key),self.assertRaises(ValueError):validate({**value,key:True})

    def test_legacy_feature_defaults(self):
        with patch.dict(os.environ,clear=True):self.assertTrue(enabled('github_write'))

    def test_package_exclusions(self):
        files=release_files()
        self.assertIn('stack/playwright/package.json',files)
        self.assertIn('web/dist/index.html',files)
        self.assertIn('cloud_entry.py',files)
        for name in files:
            self.assertFalse({'.runtime','auth.json','node_modules','.git','test-results'}.intersection(Path(name).parts),name)

    @unittest.skipUnless(os.name=='posix','Linux secret permissions')
    def test_secret_init_non_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'secrets'
            initialize(path)
            before=(path/'worker-token').read_bytes()
            with self.assertRaises(ValueError):initialize(path)
            self.assertEqual(before,(path/'worker-token').read_bytes())
            self.assertEqual((path/'worker-token').stat().st_mode & 0o777,0o640)

    def test_cloud_browser_auth_and_prefix(self):
        env={'PIPELINE_CLOUD_PROFILE':'1','PIPELINE_SUBMIT_USER':'operator','PIPELINE_SUBMIT_PASSWORD':'unit-test-secret',
             'PIPELINE_EDITOR_URL':'https://pipeline.example.com/submit/','PIPELINE_PUBLIC_BASE_URL':'https://pipeline.example.com'}
        with patch.dict(os.environ,env):
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                opener=build_opener(ProxyHandler({}))
                url='http://127.0.0.1:'+str(server.server_port)
                headers={'Host':'pipeline.example.com'}
                with self.assertRaises(HTTPError) as caught:opener.open(Request(url+'/',headers=headers))
                self.assertEqual(caught.exception.code,401)
                headers['Authorization']='Basic '+base64.b64encode(b'operator:unit-test-secret').decode()
                with opener.open(Request(url+'/',headers=headers)) as response:
                    page=response.read().decode()
                self.assertIn('/submit',page)
                self.assertNotIn('__EDITOR_API_BASE__',page)
                self.assertNotIn('unit-test-secret',page)
                bad={**headers,'X-Selection-Token':TOKEN,'Origin':'https://attacker.example'}
                with self.assertRaises(HTTPError) as caught:opener.open(Request(url+'/api/batches',b'{}',bad))
                self.assertEqual(caught.exception.code,403)
            finally:server.shutdown();thread.join();server.server_close()

    def test_native_rpc(self):
        from http.server import BaseHTTPRequestHandler
        from control_client import rpc
        class Control(BaseHTTPRequestHandler):
            def do_POST(self):
                assert self.headers['X-Worker-Token']=='unit-token'
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps(body).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Control)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch.dict(os.environ,{'PIPELINE_CONTROL_URL':'http://127.0.0.1:'+str(server.server_port),'PIPELINE_WORKER_TOKEN':'unit-token'}):
                self.assertEqual(rpc('/internal/test',{'test':True}),{'test':True})
        finally:server.shutdown();thread.join();server.server_close()


if __name__=='__main__':unittest.main()
