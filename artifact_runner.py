"""Execute exact build artifacts without rebuilding or claiming PR acceptance."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
from batch_runner import BatchRunner
from e2e_runner import EnvironmentFailure
from artifact_batches import validate


class ArtifactRunner(BatchRunner):
    def _execute_locked(self):
        try:
            super()._execute_locked()
        finally:
            if self.env:
                try:
                    self.active='report'
                    self.compose('stop')
                    self.run['environment_status']='stopped'
                    self.save()
                except Exception as error:
                    self.log('Environment stop failed: '+str(error))

    def verify_versions(self):
        # Immutable build evidence is not tied to a moving PR or branch head.
        validate(self.run['artifact_manifest'])

    def resolve(self):
        self.verify_versions()
        self.log('Robot CI image validation; not a PR merge candidate or merge approval')

    def preflight(self):
        manifest=self.run['artifact_manifest']
        expected={s:'rollingfruit/'+v[0] for s,v in self.stack.SERVICES.items()}
        if {s:v['repo'] for s,v in manifest['baseline_images'].items()}!=expected:
            raise EnvironmentFailure('Integration baseline does not cover the configured services')
        self.run['preflight']={'ok':True,'checks':[{'name':'artifact manifest','ok':True,'detail':'all services mapped'}]}
        self.save()

    def snapshot(self):
        manifest=self.run['artifact_manifest']
        root=Path(os.environ.get('PIPELINE_ARTIFACT_INBOX','/var/lib/pr-e2e/artifact-inbox')).resolve()
        self.inbox=(root/manifest['build_id']).resolve()
        if not self.inbox.is_relative_to(root):raise EnvironmentFailure('Invalid artifact directory')
        self.stack.output_json(self.artifacts/'build-manifest.json',manifest)
        self.run['input_fingerprint']=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
        harness=self.folder/'harness'
        shutil.copytree(self.stack.HERE/'playwright',harness,ignore=shutil.ignore_patterns('node_modules','results','test-results'))
        (harness/'node_modules').symlink_to(self.stack.STATE/'playwright/node_modules',target_is_directory=True)
        inputs={str(p.relative_to(harness)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in harness.rglob('*') if p.is_file() and 'node_modules' not in p.parts}
        for executable in ('multica','opencode'):
            binary=shutil.which(executable)
            if binary:
                with Path(binary).resolve().open('rb') as stream:inputs[executable]=hashlib.file_digest(stream,'sha256').hexdigest()
        self.stack.output_json(self.artifacts/'execution-inputs.json',inputs)
        for item in manifest['candidate_images'].values():
            file=(self.inbox/item['archive_name']).resolve()
            if not file.is_relative_to(self.inbox) or not file.is_file():raise EnvironmentFailure('Missing owned image archive')
            with file.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
            if actual!=item['archive_sha256']:raise EnvironmentFailure('Image archive checksum mismatch')

    def image_exists(self, image_id):
        result=subprocess.run(['docker','image','inspect','--format','{{.Id}}',image_id],capture_output=True,text=True,timeout=30)
        if result.returncode or result.stdout.strip()!=image_id:
            raise EnvironmentFailure('Frozen image is unavailable: '+image_id)

    def build(self):
        manifest=self.run['artifact_manifest']
        self.images={}
        for service,item in manifest['baseline_images'].items():
            self.image_exists(item['image_id'])
            self.images[self.stack.SERVICES[service][1]]=item['image_id']
        for item in manifest['candidate_images'].values():
            self.command(['docker','load','--input',self.inbox/item['archive_name']],timeout=1200)
            self.image_exists(item['image_id'])
        self.env=self.stack.runtime_environment(self.folder/'private',self.images)
        self.env['COMPOSE_PROJECT_NAME']='newlink-e2e-'+self.run['id']
        self.stack.output_json(self.artifacts/'image-provenance.json',manifest['baseline_images'])
        self.log('Imported exact candidate image IDs; no candidate build executed')

    def deploy(self):
        manifest=self.run['artifact_manifest']
        for service,item in manifest['candidate_images'].items():
            self.image_exists(item['image_id'])
            self.env[self.stack.SERVICES[service][1]]=item['image_id']
        self.stack.output_json(self.artifacts/'candidate-images.json',manifest['candidate_images'])
        self.compose('down','--volumes')
        self.compose('up','-d','--wait','--wait-timeout','300')
        self.command([__import__('sys').executable,self.stack.HERE/'bootstrap.py'],env=self.env,timeout=300)
        self.verify_services()
