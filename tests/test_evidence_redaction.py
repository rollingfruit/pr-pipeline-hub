import base64
import io
import json
import unittest
import zipfile
from evidence_redaction import sanitize


class EvidenceRedactionTests(unittest.TestCase):
    def archive(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            z.writestr('trace.trace',json.dumps({'params':{'value':'fixture-password'},
                'headers':[{'name':'Cookie','value':'session=private-session'}],'task_id':'keep-task'}))
        return stream.getvalue()

    def test_trace_redacts_credentials_not_correlation(self):
        with zipfile.ZipFile(io.BytesIO(sanitize(self.archive(),{'fixture-password'}))) as z:
            data=z.read('trace.trace')
        self.assertNotIn(b'fixture-password',data)
        self.assertNotIn(b'private-session',data)
        self.assertIn(b'keep-task',data)

    def test_embedded_html_report(self):
        html=b'<script>data:application/zip;base64,'+base64.b64encode(self.archive())+b'</script>'
        result=sanitize(html,{'fixture-password'})
        encoded=result.split(b'base64,')[1].split(b'<')[0]
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(encoded))) as z:
            self.assertNotIn(b'private-session',z.read('trace.trace'))

    def test_binary_media_preserved(self):
        self.assertEqual(sanitize(b'\xff\x00\x81',{'secret'}),b'\xff\x00\x81')
