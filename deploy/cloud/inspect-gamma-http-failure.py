"""Print only status and server error identifiers from private failed traces."""
import json
from pathlib import Path
import zipfile
root=Path('/var/lib/pr-e2e/gamma-diagnostics/gamma-check-20260911-174554-50b751/evidence')
for file in root.rglob('trace.zip'):
    with zipfile.ZipFile(file) as bundle:
        for name in bundle.namelist():
            if not name.endswith('.network'): continue
            for line in bundle.read(name).splitlines():
                obj=json.loads(line).get('snapshot',{})
                request=obj.get('request',{}); response=obj.get('response',{})
                if request.get('method')!='POST' or '/api/v4/posts' not in request.get('url','') or response.get('status',0)<400: continue
                content=response.get('content',{})
                body={}
                key=content.get('_sha1')
                if key:
                    try: body=json.loads(bundle.read('resources/'+key))
                    except (KeyError, ValueError): pass
                print(json.dumps({'suite':file.relative_to(root).parts[0],'status':response['status'],
                    'error':{k:body.get(k) for k in ('id','message','status_code')}}))
