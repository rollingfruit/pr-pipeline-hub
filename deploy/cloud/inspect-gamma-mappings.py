import json
import sqlite3
from pathlib import Path
root = Path('/opt/swr-push-helper')
with sqlite3.connect(root / 'data/robot-ci.db') as db:
    db.row_factory = sqlite3.Row
    print(json.dumps([dict(r) for r in db.execute('select id,name,service_id,workload_name,jump_host,nodes_json from environments')]))
catalog = json.loads((root / 'services.json').read_text())
print(json.dumps([{k:s.get(k) for k in ('id', 'image', 'docker_image', 'title')} for s in catalog]))
