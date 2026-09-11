"""One immutable multi-repository candidate in the existing E2E execution slot."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote
from e2e_runner import E2ERunner, EnvironmentFailure, AssertionFailure


class BatchRunner(E2ERunner):
    def verify_versions(self):
        from pr_pipeline_hub import utc_now
        comparisons=[]
        for m in self.run['members']:
            p=self.hub._gh_json(['api',f"repos/{m['repo']}/pulls/{m['pr_number']}"])
            base=self.hub._gh_json(['api',f"repos/{m['repo']}/git/ref/heads/{quote(p['base']['ref'],safe='')}"])['object']['sha']
            comparisons.append({'repo':m['repo'],'pr_number':m['pr_number'],'checked_at':utc_now(),
                'expected_head':m['head_sha'],'actual_head':p['head']['sha'],'expected_base':m['base_sha'],
                'actual_base':base,'state':p['state'],'draft':p.get('draft',False)})
        self.run['version_checks']=comparisons;self.save()
        if any(c['expected_head']!=c['actual_head'] or c['expected_base']!=c['actual_base'] or c['state']!='open' or c['draft'] for c in comparisons):
            self.run['stale']=True
            raise EnvironmentFailure('版本已过期：请查看预期/实际版本并重新提交')

    def resolve(self):
        self.verify_versions()
        if not self.run.get('approved_risky') and any(m.get('risky_files') for m in self.run['members']):
            raise EnvironmentFailure('构建敏感变更尚未获得本机确认')

    def preflight(self):
        result=self.stack.doctor(include_runtime=False);self.run['preflight']=result
        if not result['ok']:raise EnvironmentFailure('环境检查失败：'+', '.join(c['name'] for c in result['checks'] if c.get('required',True) and not c['ok']))
        # Freeze the trusted harness and runtime configuration before running any candidate.
        inputs={}
        for p in self.stack.HERE.rglob('*'):
            if p.is_file() and not any(x in p.parts for x in ('node_modules','__pycache__','.git')) and p.suffix in {'.py','.ts','.json','.yaml','.sh'}:
                inputs[p.relative_to(self.stack.HERE).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
        inputs['settings']=hashlib.sha256(json.dumps(self.stack.config(),sort_keys=True).encode()).hexdigest()
        for directory in ('build-inputs','cce-test-runner'):
            for p in (self.stack.STATE/directory).glob('*.json'):
                inputs[directory+'/'+p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
        if os.environ.get('DOCKER_HOST')=='unix:///run/pr-e2e/docker.sock':
            inputs['packaging_builder_image_id']=self.stack.capture(
                ['docker','image','inspect','--format','{{.Id}}','local/pr-e2e-cce-builder:20260910'])
        self.run['input_fingerprint']=hashlib.sha256(json.dumps(inputs,sort_keys=True).encode()).hexdigest()
        self.stack.output_json(self.artifacts/'trusted-inputs.json',inputs)
        shutil.copytree(self.stack.HERE/'playwright',self.folder/'harness',ignore=shutil.ignore_patterns('node_modules','results','test-results'))
        (self.folder/'harness/node_modules').symlink_to(self.stack.STATE/'playwright/node_modules',target_is_directory=True)
        self.save()

    def snapshot(self):
        self.sources={};self.baselines={};self.trees={}
        lock=self.stack.snapshot(self.folder/'sources',self.run['baseline_revisions'])
        base_images={}
        for name in self.stack.SOURCE_REPOS:
            dockerfile=self.folder/'sources'/name/'Dockerfile'
            if not dockerfile.is_file():continue
            for base in re.findall(r'^ARG \w+=(local/\S+)\s*$',dockerfile.read_text(encoding='utf-8',errors='replace'),re.MULTILINE):
                base_images[base]=self.stack.capture(['docker','image','inspect','--format','{{.Id}}',base])
        token=self.hub._github_token();env=self.hub._git_env(token)
        proxy=os.environ.get('PIPELINE_GIT_PROXY','http://127.0.0.1:15717')
        if not self.hub.git_cli.lower().endswith('.exe') and proxy:
            env.update(HTTPS_PROXY=proxy,HTTP_PROXY=proxy,https_proxy=proxy,http_proxy=proxy)
        for i,m in enumerate(self.run['members']):
            name=m['repo'].split('/')[-1];root=self.folder/'members'/name;root.parent.mkdir(exist_ok=True)
            log=self.folder/'snapshot.log'
            self.hub._checked([self.hub.git_cli,'clone','--no-checkout',f"https://github.com/{m['repo']}.git",self.hub._git_path(root)],env,log,[],attempts=3)
            self.hub._checked([self.hub.git_cli,'-C',self.hub._git_path(root),'fetch','origin',f"refs/pull/{m['pr_number']}/head"],env,log,[],attempts=3)
            self.command(['git','checkout','--detach',m['head_sha']],root)
            baseline=self.folder/'members'/(name+'-base')
            self.command(['git','clone','--no-hardlinks','--no-checkout',str(root),str(baseline)])
            self.command(['git','checkout','--detach',m['base_sha']],baseline)
            try:
                self.command(['git','-c','user.name=Pipeline','-c','user.email=pipeline@localhost','merge','--no-commit','--no-ff',m['base_sha']],root)
            except EnvironmentFailure:
                conflicts=self.stack.git(root,'diff','--name-only','--diff-filter=U').splitlines()
                if conflicts:
                    self.run.setdefault('merge_conflicts',[]).extend(name+'/'+f for f in conflicts)
                    raise AssertionFailure('联合候选存在合并冲突：'+name)
                raise
            self.sources[name]=root;self.baselines[name]=baseline;self.trees[name]=self.stack.git(root,'write-tree')
            lock['services'][name]['sha']=m['base_sha']
            for directory in (baseline,root):
                dockerfile=directory/'Dockerfile'
                if dockerfile.is_file():
                    for base in re.findall(r'^ARG \w+=(local/\S+)\s*$',dockerfile.read_text(encoding='utf-8',errors='replace'),re.MULTILINE):
                        base_images[base]=self.stack.capture(['docker','image','inspect','--format','{{.Id}}',base])
        lock['local_base_images']=base_images
        self.run['input_fingerprint']=hashlib.sha256(json.dumps({'trusted':self.run['input_fingerprint'],
            'assets':{n:s['assets'] for n,s in lock['services'].items()},'base_images':base_images},sort_keys=True).encode()).hexdigest()
        lock['members']=[{**m,'candidate_tree':self.trees[m['repo'].split('/')[-1]]} for m in self.run['members']]
        self.run['candidate_trees']=self.trees
        self.stack.output_json(self.artifacts/'sources.lock.json',lock);self.save()

    def agent_review(self):
        if not self.run['options']['codex_review']:
            self.run['review']={'status':'disabled','summary':'未启用代码检视；不影响真实 Agent E2E','findings':[]};return
        from local_agent_review import review
        reviews=[]
        for m in self.run['members']:
            result=review(self,{**m,'workspace':str(self.sources[m['repo'].split('/')[-1]])})
            reviews.append({'repo':m['repo'],**result})
        self.run['review']={'status':'completed','summary':'逐仓检视完成；建议用例未自动改变本次集合','members':reviews,
            'findings':[{**f,'file':r['repo']+'/'+f['file']} for r in reviews for f in r['findings']]}

    def build(self):
        self.images={};provenance={}
        for service,(name,variable,_) in self.stack.SERVICES.items():
            m=next((m for m in self.run['members'] if m['repo'].endswith('/'+name)),None)
            sha=m['base_sha'] if m else self.run['baseline_revisions'][name]
            source=self.baselines[name] if m else self.stack.ROOT/name
            image=f'local/pr-e2e-{service}:{sha[:12]}'
            record_path=self.stack.STATE/'build-contexts'/f'{name}-{sha[:12]}'/'build.json'
            record=json.loads(record_path.read_text()) if record_path.exists() else {}
            probe=subprocess.run(['docker','image','inspect','--format','{{.Id}}',image],capture_output=True,text=True)
            if not(record.get('batch_input_fingerprint')==self.run['input_fingerprint'] and record.get('source_sha')==sha and record.get('exit_code')==0 and probe.returncode==0 and record.get('image_id')==probe.stdout.strip()):
                self.command([sys.executable,self.stack.HERE/'build-service.py',service,'--source',source,'--revision',sha],timeout=14400)
                record=json.loads(record_path.read_text());record['batch_input_fingerprint']=self.run['input_fingerprint'];self.stack.output_json(record_path,record)
            self.images[variable]=record['image_id'];provenance[service]=record
        self.stack.output_json(self.artifacts/'image-provenance.json',provenance)
        self.env=self.stack.runtime_environment(self.folder/'private',self.images)
        self.env['COMPOSE_PROJECT_NAME']='newlink-e2e-'+self.run['id']

    def baseline(self):
        runtime=self.stack.doctor();self.run['runtime_preflight']=runtime;self.save()
        if not runtime['ok']:
            raise EnvironmentFailure('用例运行依赖未就绪（不是代码检视）：'+', '.join(c['name'] for c in runtime['checks'] if not c['ok']))
        # Reuse cleanup/readiness but run precisely the selected suites, including contracts.
        selected=self.run['suites'];self.run['suites']=[]
        try:super().baseline()
        finally:self.run['suites']=selected
        if self.run['options']['baseline_enabled']:
            for s in selected:self.test_suite(s['id'],baseline=True)

    def deploy(self):
        provenance={}
        for m in self.run['members']:
            name=m['repo'].split('/')[-1]
            service=next(s for s,(n,_,_) in self.stack.SERVICES.items() if n==name)
            tree=self.trees[name]
            self.command([sys.executable,self.stack.HERE/'build-service.py',service,'--source',self.sources[name],
                          '--revision',tree,'--image',f"local/pr-e2e-{service}:{self.run['id']}"],timeout=14400)
            record=json.loads((self.stack.STATE/'build-contexts'/f'{name}-{tree[:12]}'/'build.json').read_text())
            self.env[self.stack.SERVICES[service][1]]=record['image_id'];provenance[service]=record
        self.stack.output_json(self.artifacts/'candidate-images.json',provenance)
        self.compose('down','--volumes');self.compose('up','-d','--wait','--wait-timeout','300')
        self.command([sys.executable,self.stack.HERE/'bootstrap.py'],env=self.env,timeout=300);self.verify_services()

    def publish(self,state):
        self.run['github']={'state':'outbox_pending' if self.run['options']['github_write'] else 'disabled','ok':False}
        self.save()

    def report(self,verify=True):
        if verify:
            try:self.verify_versions()
            except Exception as e:self.failure_kind='error';self.run['error']=str(e)
        super().report(verify=False)
        self.stack.output_json(self.artifacts/'batch-manifest.json',{k:self.run.get(k) for k in ('members','options','baseline_revisions','candidate_trees','input_fingerprint','version_checks','suites','full_acceptance','stale','error')})

    def _execute_locked(self):
        from pr_pipeline_hub import utc_now
        self.run.update(status='running',started_at=utc_now(),test_results=[],environment_status='not_started');self.save()
        try:
            for name,action in [('resolve',self.resolve),('preflight',self.preflight),('snapshot',self.snapshot),('agent',self.agent_review),('build',self.build),('baseline',self.baseline),('deploy',self.deploy)]:
                self.stage(name,action)
                if name=='agent' and not self.run['options']['codex_review']:self.hub._stage(self.run,name)['conclusion']='skipped'
                if name=='baseline' and not self.run['options']['baseline_enabled']:self.hub._stage(self.run,name)['name']='环境准备（基线对照未启用）'
            for s in self.run['suites']:self.stage(s['id'],lambda s=s:self.test_suite(s['id']))
            self.failure_kind='success'
        except Exception as e:
            self.failure_kind='failure' if isinstance(e,AssertionFailure) and self.active!='baseline' else 'error'
            self.run.update(error=str(e),failure_stage=self.active,baseline_issue=self.active=='baseline')
            self.log(str(e));self.hub._skip_remaining(self.run,self.active)
        finally:
            try:self.stage('report',self.report)
            except Exception as e:self.failure_kind='error';self.run['error']=str(e)
            self.run['failure_kind']=self.failure_kind
            self.publish(self.failure_kind)
            self.hub._stage(self.run,'github').update(status='completed',conclusion='skipped')
            self.hub._finish(self.run,'success' if self.failure_kind=='success' else 'failure',
                '联合验证通过，仅适用于本次组合与所选用例' if self.failure_kind=='success' else '联合验证未通过：'+self.run.get('error',''))
            self.report(verify=False)
