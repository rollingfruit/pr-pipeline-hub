import sys
sys.path.insert(0, '/opt/pr-pipeline-ci')
from gamma_access import GammaAccess
access = GammaAccess('a5932430eb2f')
for name in ('agent-link', 'multica-server'):
    output = access.remote('kubectl -n default logs deployment/' + name + ' --since=30m --tail=1000')
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if any(word in line for word in ('request failed', 'request crashed', 'Traceback', 'delete', 'ERROR', 'RuntimeError:', 'agents/delete')):
            print(name, '\n'.join(lines[max(0, index-1):index+6]))
output = access.remote('kubectl -n default exec deployment/agent-link -- tail -n 200 /opt/ai/agentlink/logs/error.log')
lines = output.splitlines()
for index, line in enumerate(lines):
    if any(word in line for word in ('delete', 'Traceback', 'RuntimeError', '503', 'cq7pdb')):
        print('\n'.join(lines[max(0, index-2):index+9]))
