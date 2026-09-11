import re
import sys
sys.path.insert(0,'/opt/pr-pipeline-ci')
from gamma_access import GammaAccess
access=GammaAccess('a5932430eb2f')
try:
    for name in ('governance','multica-server'):
        directory = 'agent-governance-gateway' if name == 'governance' else 'multica-server'
        text=access.remote("kubectl -n default exec deployment/"+name+" -- sh -c 'tail -n 3000 /opt/ai/"+directory+"/logs/*.log 2>/dev/null || true'",timeout=45)
        lines=[s for s in text.splitlines() if any(k in s for k in ('3985b0c0','hjqpaxx9','callback failed','delivery failed','deliver failed'))]
        print(name)
        for line in lines[-15:]:
            print(re.sub(r'(?i)(token|password|authorization)([=:]\\?"?)[^ ,"]+',r'\1\2[REDACTED]',line)[:1100])
finally: access.close()
