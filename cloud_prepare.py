"""Offline release packaging and explicit, non-destructive Linux setup checks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent
EXCLUDED = {'.runtime', '.git', '__pycache__', 'node_modules', 'results', 'test-results', 'playwright-report'}


def release_files(root=ROOT):
    files = {p.name:p for p in root.glob('*.py')}
    files.update({name:root/name for name in ('CLOUD-DEPLOYMENT.md','BATCHES.md')})
    files['control_requirements.txt'] = root/'control_requirements.txt'
    for folder in ('deploy/cloud', 'static', 'web/dist'):
        for p in (root/folder).rglob('*'):
            if p.is_file() and not p.is_symlink() and not EXCLUDED.intersection(p.relative_to(root).parts):
                files[p.relative_to(root).as_posix()] = p
    stack = root.parent/'mattermost-microservice/infra/pr-e2e'
    for p in stack.rglob('*'):
        if p.is_file() and not p.is_symlink() and not EXCLUDED.intersection(p.relative_to(stack).parts) and p.suffix in {'.py','.ts','.json','.yaml','.sh','.cjs','.md'}:
            files['stack/'+p.relative_to(stack).as_posix()] = p
    if 'web/dist/index.html' not in files or 'stack/stack.py' not in files:
        raise ValueError('Build frontend and include the trusted E2E harness before packaging')
    return files


def bundle(output):
    files=release_files()
    manifest={'format':1, 'runtime_verified':False,
              'files':{name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in sorted(files.items())}}
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():raise ValueError('Output already exists; choose a new release filename')
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'release-manifest.json'
        path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        with tarfile.open(output,'w:gz') as archive:
            for name,p in sorted(files.items()):archive.add(p,arcname=name,recursive=False)
            archive.add(path,arcname=path.name)
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix+'.sha256').write_text(digest+'  '+output.name+'\n')
    print(json.dumps({'bundle':str(output),'sha256':digest,'files':len(files),'runtime_verified':False}))


def initialize(directory):
    if os.name!='posix':raise ValueError('Initialize secrets on the target Linux host only')
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True,mode=0o750)
    # Refuse partial overwrites, including replacing a live database password.
    names=('worker-token','submit-password','postgres-password','database-url')
    if any((directory/n).exists() for n in names):raise ValueError('Secret files already exist; no files changed')
    password=secrets.token_urlsafe(36)
    values={'worker-token':secrets.token_urlsafe(48),'submit-password':secrets.token_urlsafe(32),
            'postgres-password':password,'database-url':'postgresql://prpipeline:'+password+'@127.0.0.1:5439/prpipeline'}
    for name,value in values.items():
        fd=os.open(directory/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o640)
        with os.fdopen(fd,'w') as target:target.write(value+'\n')
    print('Created secret files; values are not printed. Assign the documented service group before startup.')


def verify(bundle_path):
    path=Path(bundle_path)
    expected=path.with_suffix(path.suffix+'.sha256').read_text().split()[0]
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('Bundle checksum mismatch')
    with tarfile.open(path,'r:gz') as archive:
        files={}
        for member in archive:
            relative=Path(member.name)
            if not member.isfile() or relative.is_absolute() or '..' in relative.parts or member.name in files:
                raise ValueError('Unsafe or duplicate release member')
            files[member.name]=hashlib.sha256(archive.extractfile(member).read()).hexdigest()
        manifest=json.load(archive.extractfile('release-manifest.json'))
        files.pop('release-manifest.json')
        if files!=manifest['files']:raise ValueError('Release file checksum mismatch')
    print(json.dumps({'bundle_verified':True,'files':len(files),'runtime_verified':False}))


def doctor(config):
    from cloud_config import load,activate
    cfg=load(config,'worker',True)
    activate(cfg,'worker')
    sys.path.insert(0,cfg['paths']['stack'])
    import stack
    checks=[]
    for program in ('gh',stack.config().get('AGENT_PROVIDER','codex'),'multica'):
        import shutil
        checks.append({'name':program,'ok':bool(shutil.which(program))})
    try:
        result=subprocess.run(['gh','auth','status'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
        checks.append({'name':'github-auth','ok':result.returncode==0})
    except (OSError,subprocess.TimeoutExpired):checks.append({'name':'github-auth','ok':False})
    report=stack.doctor()
    report['checks'].extend(checks)
    report['ok']=all(c['ok'] for c in report['checks'])
    report['e2e_verified']=False
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['ok'] else 2


def main():
    parser=argparse.ArgumentParser()
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('bundle').add_argument('--output',type=Path,required=True)
    commands.add_parser('verify').add_argument('--bundle',type=Path,required=True)
    commands.add_parser('init-secrets').add_argument('--directory',type=Path,default=Path('/etc/pr-pipeline/secrets'))
    commands.add_parser('doctor').add_argument('--config',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='bundle':bundle(args.output)
    elif args.command=='verify':verify(args.bundle)
    elif args.command=='init-secrets':initialize(args.directory)
    else:return doctor(args.config)
    return 0


if __name__=='__main__':sys.exit(main())
