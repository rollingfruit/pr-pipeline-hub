"""Extract scoped task lifecycle evidence without exporting prompts or credentials."""
import argparse
import json
import re
from pathlib import Path

AGENT = '2b6d5bef-1a74-4e13-8638-eb64ea35e869'
WORKSPACE = 'f599cfe5-bc2b-4900-bf05-5e2dbe18a431'
FIELD = re.compile(r'(\w+)=("(?:\\.|[^"\\])*"|\S+)')


def inspect(lines, task_id):
    events = []
    for line in lines:
        fields = {}
        for key, value in FIELD.findall(line):
            if value.startswith('"'):
                try:
                    value = json.loads(value)
                except ValueError:
                    continue
            fields[key] = value
        if (fields.get('task_id'), fields.get('agent_id'), fields.get('workspace_id')) != (task_id, AGENT, WORKSPACE):
            continue
        message = fields.get('msg', '')
        if message not in {'task received', 'picked chat task', 'task failed', 'task completed'}:
            continue
        error_code = 'empty_im_task_prompt' if 'im_task_prompt is empty' in fields.get('error', '') else None
        events.append({
            'time': fields.get('time'), 'event': message,
            'runtime_id': fields.get('runtime_id'),
            'chat_session_id': fields.get('chat_session_id'),
            'channel_id': fields.get('channel_id'),
            'provider': fields.get('provider'), 'error_code': error_code,
        })
    failed = any(e['event'] == 'task failed' for e in events)
    return {'task_id': task_id, 'events': events,
            'execution': 'failed' if failed else 'observed' if events else 'unknown',
            'final_group_reply': 'not_verified',
            'note': 'Daemon evidence does not prove a final IM delivery. Verify the group separately.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--log', type=Path, default=Path.home()/'.multica/daemon.log')
    args = parser.parse_args()
    with args.log.open(encoding='utf-8', errors='replace') as stream:
        print(json.dumps(inspect(stream, args.task_id), indent=2))
