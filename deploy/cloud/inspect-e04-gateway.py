import sys
sys.path.insert(0,'/opt/pr-pipeline-ci')
from gamma_access import GammaAccess
a=GammaAccess('a5932430eb2f')
try:
    text=a.remote("kubectl -n default exec deployment/semantic-gateway -- sh -c 'tail -n 1600 /opt/ai/semantic-gateway/logs/*.log 2>/dev/null || true'")
    lines=[x for x in text.splitlines() if any(v in x.lower() for v in ('safety','injection','blocked','blacklist'))]
    for line in lines[-25:]: print(line[:1400])
finally:a.close()
