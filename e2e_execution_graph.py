"""Deterministic E2E dependency graph with a hard two-process ceiling."""
from collections import defaultdict

DEPENDENCIES = {
    'E01': (),
    'E02': ('E01',),
    'E03': ('E01',),
    'E04': ('E02', 'E03'),
    'E06': ('E02', 'E03'),
    'E05': ('E04', 'E06'),
}
EXCLUSIVE = {'E05'}


def waves(selected, max_parallel=2):
    if not 1 <= max_parallel <= 2:
        raise ValueError('E2E parallelism must be between 1 and 2')
    selected = list(dict.fromkeys(selected))
    unknown = set(selected) - set(DEPENDENCIES)
    if unknown:
        raise ValueError('Unknown E2E suites: ' + ', '.join(sorted(unknown)))
    remaining = set(selected)
    completed = set(DEPENDENCIES) - remaining
    result = []
    while remaining:
        ready = sorted(s for s in remaining if set(DEPENDENCIES[s]) <= completed)
        if not ready:
            raise ValueError('Selected suites have unresolved dependencies')
        exclusive = next((s for s in ready if s in EXCLUSIVE), None)
        wave = [exclusive] if exclusive else ready[:max_parallel]
        result.append(wave)
        remaining.difference_update(wave)
        completed.update(wave)
    return result
