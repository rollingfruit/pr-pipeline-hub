"""Single-workload rollout with optimistic concurrency and scoped image rollback."""
import copy
import json
from pathlib import Path
import re
import shlex


class GammaRollout:
    def __init__(self, access, manifest, private):
        self.access, self.manifest, self.private = access, manifest, Path(private)
        self.before = self.expected = None
        self.applied = False

    def prepare(self):
        row = self.manifest['result']
        env = self.access.environment
        if env.get('service_id') != row['service_id'] or not row.get('ok'):
            raise ValueError('Build service does not match the selected environment')
        if not re.fullmatch(r'[0-9a-f]{40}', row.get('commit_sha', '')):
            raise ValueError('Full build SHA required')
        image = self.manifest['pinned_image']
        if not re.fullmatch(r'swr\.cn-southwest-2\.myhuaweicloud\.com/public_ai/[a-z0-9-]+@sha256:[0-9a-f]{64}', image):
            raise ValueError('Verified immutable SWR image required')
        self.deploy, preferred = self.access.adapter.resolve_deploy_target(row['service_id'], image, env['workload_name'])
        self.before = self.access.resource('deployment', self.deploy)
        containers = self.before['spec']['template']['spec']['containers']
        name = self.access.adapter.pick_container([(c['name'], c['image']) for c in containers], image=image, preferred=preferred)
        self.index = next(i for i, c in enumerate(containers) if c['name'] == name)
        self.old_image = containers[self.index]['image']
        self.expected = copy.deepcopy(self.before['spec']['template'])
        self.expected['spec']['containers'][self.index]['image'] = image
        snapshot = self.private / 'rollout-before.json'
        snapshot.write_text(json.dumps(self.before))
        snapshot.chmod(0o600)
        return {'deployment': self.deploy, 'container': name, 'before': self.old_image, 'after': image}

    def patch(self, obj, image):
        operations = [{'op': 'test', 'path': '/metadata/uid', 'value': obj['metadata']['uid']},
                      {'op': 'test', 'path': '/metadata/resourceVersion', 'value': obj['metadata']['resourceVersion']},
                      {'op': 'replace', 'path': f'/spec/template/spec/containers/{self.index}/image', 'value': image}]
        command = 'kubectl -n %s patch deployment %s --type=json -p %s' % (
            shlex.quote(self.access.namespace), shlex.quote(self.deploy), shlex.quote(json.dumps(operations)))
        self.access.remote(command)

    def wait(self):
        self.access.remote('kubectl -n %s rollout status deployment/%s --timeout=240s' % (
            shlex.quote(self.access.namespace), shlex.quote(self.deploy)), timeout=270)

    def apply(self):
        # Mark attempted first: an SSH response can be lost after Kubernetes accepts the patch.
        self.applied = True
        self.patch(self.before, self.manifest['pinned_image'])
        self.wait()

    def rollback(self):
        current = self.access.resource('deployment', self.deploy)
        if current['metadata']['uid'] != self.before['metadata']['uid']:
            raise RuntimeError('Deployment replaced externally; automatic rollback refused')
        if current['spec']['template'] == self.before['spec']['template']:
            return 'unchanged'
        if current['spec']['template'] != self.expected:
            raise RuntimeError('Deployment changed externally; automatic rollback refused')
        self.patch(current, self.old_image)
        self.wait()
        return 'restored'
