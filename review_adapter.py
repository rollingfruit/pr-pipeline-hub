"""Read-only projection of immutable legacy artifacts and live review records."""
import json
from pathlib import Path
from pr_pipeline_hub import redact


def enrich(run, runs_dir):
    value = dict(run)
    root = (Path(runs_dir) / run['id'] / 'artifacts').resolve()
    evidence = []
    for file in sorted(root.glob('*/*/evidence.json')):
        try:
            payload = json.loads(file.read_text())
        except (OSError, ValueError):
            continue
        phase, suite = file.relative_to(root).parts[:2]
        for test in payload.get('tests', []):
            attachments = []
            for item in test.get('evidence', []):
                target = (file.parent / item.get('path', '')).resolve()
                if target.is_file() and target.is_relative_to(root):
                    attachments.append({'name': item.get('name', target.name),
                        'url': f"/artifacts/{run['id']}/{target.relative_to(root).as_posix()}",
                        'type': 'video' if target.suffix == '.webm' else 'image' if target.suffix in {'.png', '.jpg'} else 'file'})
            evidence.append({**test, 'phase': phase, 'suite': suite, 'attachments': attachments,
                             'errors': [redact(str(e)) for e in test.get('errors', [])]})
    value['evidence_cases'] = evidence
    value['observation_mode'] = True
    value.setdefault('review', {'status': 'not_recorded', 'findings': [], 'summary': '尚无结构化 Agent 检视记录'})
    value.setdefault('deliveries', [{'channel': 'github_status', **value.get('github', {})},
                                  {'channel': 'github_comment', 'state': 'not_recorded'},
                                  {'channel': 'newlink', 'state': 'not_recorded'}])
    if value.get('kind')=='batch' and value.get('options',{}).get('github_write'):
        expected={f'batch_{kind}:{m["repo_id"]}' for m in value['members'] for kind in ('status','comment')}
        final=[d for d in value['deliveries'] if d.get('phase')=='final']
        confirmed={d['channel'] for d in final if d.get('ok')}
        stage=next((s for s in value.get('stages',[]) if s['id']=='github'),None)
        if stage:
            stage=dict(stage)
            stage.update(name='GitHub 结果投递',status='completed' if expected<=confirmed else 'queued',
                         conclusion='success' if expected<=confirmed else None)
            value['stages']=[stage if s['id']=='github' else s for s in value['stages']]
        value['github']={'ok':expected<=confirmed,'state':'delivered' if expected<=confirmed else 'outbox_pending'}
    return value
