"""Require the desired Deployment revision, not merely an available old replica."""
import time


def wait_for_deployments(access, required, timeout=90):
    deadline = time.monotonic() + timeout
    while True:
        try:
            deployments = access.resource('deployments')['items']
            pods = access.resource('pods')['items']
            replica_sets = access.resource('replicasets')['items']
            missing = required - {d['metadata']['name'] for d in deployments}
            if missing:
                raise RuntimeError('Required deployments missing: ' + ', '.join(sorted(missing)))
            return [deployment_evidence(d, pods, replica_sets) for d in deployments if d['metadata']['name'] in required]
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)


def deployment_evidence(deployment, pods, replica_sets):
    name = deployment['metadata']['name']
    wanted = deployment['spec'].get('replicas', 1)
    state = deployment.get('status', {})
    if wanted < 1 or state.get('observedGeneration', 0) < deployment['metadata']['generation']:
        raise RuntimeError(name + ': deployment generation is not ready')
    if any(state.get(key, 0) != wanted for key in ('replicas', 'updatedReplicas', 'readyReplicas', 'availableReplicas')):
        raise RuntimeError(name + ': rollout incomplete; an old replica may still be serving')
    owned = {r['metadata']['uid'] for r in replica_sets if any(
        ref.get('uid') == deployment['metadata']['uid'] for ref in r['metadata'].get('ownerReferences', []))}
    live = [p for p in pods if not p['metadata'].get('deletionTimestamp') and any(
        ref.get('uid') in owned for ref in p['metadata'].get('ownerReferences', []))]
    if len(live) != wanted:
        raise RuntimeError(name + ': active pod count differs from desired replicas')
    expected = {c['name']: c['image'] for c in deployment['spec']['template']['spec']['containers']}
    evidence = []
    for pod in live:
        requested = {c['name']: c['image'] for c in pod['spec']['containers']}
        status = {c['name']: c for c in pod.get('status', {}).get('containerStatuses', [])}
        if requested != expected or any(not status.get(c, {}).get('ready') or not status.get(c, {}).get('imageID') for c in expected):
            raise RuntimeError(name + ': pod image or readiness does not match the frozen Deployment')
        evidence.append({'pod': pod['metadata']['name'], 'node': pod['spec'].get('nodeName'),
            'containers': [{'name': c, 'requested_image': expected[c], 'image_id': status[c]['imageID']} for c in expected]})
    return {'deployment': name, 'generation': deployment['metadata']['generation'], 'pods': evidence}
