"""Trusted selection policy; never execute policy from a PR checkout."""
from pathlib import PurePosixPath
from e2e_catalog import CATALOG, CORE

VERSION = '2026-09-v1'
REPOSITORIES = ('service_router', 'multica-aiwelink', 'mattermost', 'AgentLink', 'public-service',
                'observability', 'skills-market', 'agent-governance-gw', 'CellMem',
                'semantic-schedule', 'semantic-gateway', 'aiwelink-temporal')
DIRECT_SERVICES = {'agent-governance-gw', 'semantic-schedule', 'semantic-gateway', 'service_router',
                   'multica-aiwelink', 'AgentLink'}


def select(repo, files, additions=()):
    names = [str(p).replace('\\', '/') for p in files]
    reasons = {s: ['核心能力必跑'] for s in CORE}
    if repo.split('/')[-1] in DIRECT_SERVICES and any(
        p.startswith(('internal/', 'src/', 'scripts/', 'conf/')) for p in names):
        for suite in ('DR', 'DR-contract'):
            reasons[suite] = ['路由、消息或直答服务实现发生变化']
    known = {s['id'] for s in CATALOG if s['implemented']}
    for suite in additions:
        if suite not in known:
            raise ValueError('Agent requested unknown/unimplemented suite')
        reasons.setdefault(suite, []).append('Agent 补充')
    risky = [p for p in names if PurePosixPath(p).name.lower().startswith('dockerfile')
             or p.endswith(('.sh', '.ps1', '.bat', '.cmd'))
             or p.startswith(('build/', 'docker/', '.github/', 'scripts/'))
             or PurePosixPath(p).name in {'Makefile', 'package.json', 'go.mod', 'go.sum'}]
    gaps = ['停止/取消、产物下载、权限隔离专项尚未建设']
    if repo.endswith('/observability'):
        gaps.append('可观测性业务专项未覆盖；健康检查不等于业务验收')
    return {'version': VERSION, 'suites': [{**s, 'reason': '；'.join(reasons[s['id']])}
            for s in CATALOG if s['id'] in reasons], 'risky_files': risky, 'coverage_gaps': gaps}
