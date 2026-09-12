"""First-attempt statistics; never discard infrastructure failures from denominators."""
from collections import Counter


def statistics(rounds, started, planned, active=False):
    passed = sum(row.get('first_pass') is True for row in rounds)
    failures = Counter(row.get('failure_kind', 'unknown') for row in rounds if not row.get('first_pass'))
    running = int(active and started > len(rounds))
    interrupted = max(0, started - len(rounds) - running)
    if interrupted:
        failures['interrupted'] += interrupted
    suites = {}
    for row in rounds:
        for case in row.get('tests', []):
            key = case.get('suite', '?') + ':' + case.get('id', case.get('title', '?'))
            stat = suites.setdefault(key, {'started': 0, 'passed': 0, 'failed': 0})
            stat['started'] += 1
            stat['passed' if case.get('status') == 'passed' else 'failed'] += 1
    return {'planned': planned, 'started': started, 'completed': len(rounds), 'interrupted': interrupted, 'running': running,
            'first_pass_count': passed, 'first_pass_rate': passed / started if started else None,
            'failure_types': dict(failures), 'cases': suites}
