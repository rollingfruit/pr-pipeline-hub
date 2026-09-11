"""Explicit cloud profile; legacy WSL services are unchanged unless loaded."""
import os
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

FEATURES = ('code_review', 'github_write', 'monitor', 'newlink')


def load(path, role=None, check_files=False):
    path=Path(path).resolve()
    with path.open('rb') as source: cfg=tomllib.load(source)
    if cfg.get('version')!=1: raise ValueError('Unsupported cloud config version')
    if type(cfg.get('allow_private_http',False)) is not bool: raise ValueError('allow_private_http must be boolean')
    import re
    repos=cfg.get('repositories',[])
    if not isinstance(repos,list) or not repos or any(not isinstance(r,str) or not re.fullmatch(r'[\w.-]+/[\w.-]+',r) for r in repos):
        raise ValueError('repositories must contain owner/repository names')
    for section in ('urls','paths','features','secrets'): cfg.setdefault(section,{})
    for key in FEATURES:
        if type(cfg['features'].get(key,False)) is not bool: raise ValueError('Feature must be boolean: '+key)
    if cfg['features'].get('newlink'):
        raise ValueError('Cloud NewLink adapter is not certified; leave this optional integration disabled')
    for key in ('public','control'):
        url=urlsplit(cfg['urls'].get(key,''))
        if url.scheme not in {'https','http'} or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in {'','/'} or any(c in cfg['urls'][key] for c in '<>"\'\\\r\n '):
            raise ValueError('Invalid URL: '+key)
        if url.scheme!='https' and url.hostname not in {'127.0.0.1','localhost'} and not cfg.get('allow_private_http',False):
            raise ValueError('HTTPS required, or explicitly allow isolated private HTTP: '+key)
    for key in ('workspace','state','data','archives','stack','runtime_settings'):
        if not Path(cfg['paths'].get(key,'')).is_absolute(): raise ValueError('Absolute path required: '+key)
    required={'control':('worker_token','database_url'), 'editor':('worker_token','submit_password'),
              'worker':('worker_token',), 'monitor':('worker_token',), 'register':('worker_token',),
              'publisher':('worker_token',), 'check':('worker_token','submit_password','database_url')}.get(role,())
    for key in required:
        secret=cfg['secrets'].get(key,'')
        if not secret: raise ValueError('Secret file required: '+key)
        if check_files and (not Path(secret).is_file() or not Path(secret).read_text().strip()):
            raise ValueError('Missing/empty secret file: '+key)
    cfg['_file']=str(path)
    return cfg


def activate(cfg, role):
    paths=cfg['paths']; urls=cfg['urls']; features=cfg['features']
    env={'PIPELINE_CLOUD_PROFILE':'1','PIPELINE_CONTROL_MODE':'ecs',
         'PIPELINE_CONTROL_URL':urls['control'].rstrip('/'),'PIPELINE_PUBLIC_BASE_URL':urls['public'].rstrip('/'),
         'PIPELINE_EDITOR_URL':urls['public'].rstrip('/')+'/submit/',
         'PIPELINE_DATA_DIR':paths['data'],'PIPELINE_ARCHIVE_ROOT':paths['archives'],
         'PIPELINE_E2E_ROOT':paths['stack'],'E2E_STATE_DIR':paths['state'],
         'E2E_WORKSPACE_ROOT':paths['workspace'],'E2E_SETTINGS_FILE':paths['runtime_settings'],
         'PIPELINE_PUBLIC_READ':'true','PIPELINE_EMBED_VIEW_TOKEN':'false',
         'PIPELINE_GIT_PROXY':cfg.get('git_proxy',''),
         'PIPELINE_EXECUTION_LOCATION':'Cloud Linux Worker',
         'PIPELINE_WORKER_ID':cfg.get('worker_id','cloud-linux-1'),
         'PIPELINE_SUBMIT_USER':cfg.get('submit_user','operator'),
         'PIPELINE_EDITOR_BIND':cfg.get('editor_bind','127.0.0.1'),
         'PIPELINE_ALLOW_PRIVATE_HTTP':str(cfg.get('allow_private_http',False)).lower()}
    for key in FEATURES:env['PIPELINE_FEATURE_'+key.upper()]=str(features.get(key,False)).lower()
    env['PIPELINE_WORKER_PORT']=str(cfg.get('worker_port',8788))
    if cfg.get('docker_host'):
        if cfg['docker_host']!='unix:///run/pr-e2e/docker.sock':raise ValueError('CI profile requires its isolated Docker socket')
        env['DOCKER_HOST']=cfg['docker_host']
        env['PIPELINE_RESOURCE_GATE']='true'
        env['PIPELINE_MIN_MEMORY_GIB']='12'
        env['PIPELINE_MIN_DISK_GIB']='60'
        env['PIPELINE_DOCKER_CGROUP_PARENT']='/pr.slice/pr-e2e.slice'
    secret_map={'worker_token':'PIPELINE_WORKER_TOKEN','submit_password':'PIPELINE_SUBMIT_PASSWORD',
                'database_url':'PIPELINE_DATABASE_URL','github_token':'GH_TOKEN'}
    needed={'control':('worker_token','database_url'),'editor':('worker_token','submit_password','github_token'),
            'worker':('worker_token','github_token'),'publisher':('worker_token',)}.get(role,())
    for key in needed:
        file=cfg['secrets'].get(key)
        if file:env[secret_map[key]]=Path(file).read_text().strip()
    os.environ.update(env)


def enabled(name):
    return os.environ.get('PIPELINE_CLOUD_PROFILE')!='1' or os.environ.get('PIPELINE_FEATURE_'+name.upper())=='true'
