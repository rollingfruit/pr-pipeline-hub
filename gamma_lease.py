"""Online environment fencing, called before each shared-cluster mutation."""
import json
import os
from pathlib import Path


def check():
    from control_client import rpc
    claim_path = os.environ.get('GAMMA_LEASE_FILE')
    if not claim_path:
        raise PermissionError('Gamma must be submitted to the persistent queue')
    claim = json.loads(Path(claim_path).read_text())
    return rpc('/internal/gamma/' + claim['id'] + '/lease', {
        'lease_token': claim['lease_token'], 'generation': claim['generation']})
