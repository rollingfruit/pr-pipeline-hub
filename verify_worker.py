"""Exercise the real SSH/lease transport without executing PR code or posting feedback."""
import json
from control_client import rpc

result = rpc('/api/runs')
print(json.dumps({'ssh_control_connected':True, 'records':len(result['runs'])}))
