"""Ask GitHub to send fresh real ping deliveries, after network rules are fixed."""
import json
import os
import subprocess
from pathlib import Path
from pr_pipeline_hub import PipelineHub

os.environ['PIPELINE_NO_WORKER']='1'
root=Path(__file__).resolve().parent
hub=PipelineHub(root/'.runtime/registry-tool')
for record in json.loads((root/'.runtime/webhooks.json').read_text()):
    result=subprocess.run([hub.gh_cli,'api',f"repos/{record['repo']}/hooks/{record['hook_id']}/pings",'--method','POST'],
                          capture_output=True,text=True,timeout=45)
    if result.returncode:
        raise RuntimeError('Ping request rejected: '+record['repo'])
    print('Ping requested: '+record['repo'],flush=True)
