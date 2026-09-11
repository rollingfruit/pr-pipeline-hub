"""E2E profile for Pipeline Hub. All failures retain evidence and fail closed."""
from __future__ import annotations

import hashlib
import html
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import time

from e2e_catalog import CORE, validate_result


class EnvironmentFailure(RuntimeError):
    pass


class AssertionFailure(RuntimeError):
    pass


def load_stack():
    path = Path(os.environ.get("PIPELINE_E2E_ROOT", Path(__file__).resolve().parent.parent /
                               "mattermost-microservice/infra/pr-e2e")) / "stack.py"
    spec = importlib.util.spec_from_file_location("local_e2e_stack", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class E2ERunner:
    def __init__(self, hub, run):
        self.hub, self.run = hub, run
        self.folder = hub.runs_dir / run["id"]
        self.artifacts = self.folder / "artifacts"
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.active = None
        self.stack = load_stack()
        self.env = None
        self.failure_kind = "error"
        self.steps = []

    def save(self):
        with self.hub.lock:
            self.hub._save(self.run)

    def log(self, message):
        from pr_pipeline_hub import redact
        name = self.active or "report"
        with (self.folder / f"{name}.log").open("a", encoding="utf-8") as out:
            out.write(redact(str(message)) + "\n")

    def command(self, argv, cwd=None, env=None, timeout=3600):
        self.log("$ " + " ".join(str(x) for x in argv))
        stage = self.hub._stage(self.run, self.active)
        # Reuse the Hub's streaming process runner and hard timeout.
        ok = self.hub._command_stage(self.run, self.active, [str(x) for x in argv],
                                     Path(cwd or self.stack.HERE), env or os.environ.copy(), timeout,
                                     manage_stage=False, append=True)
        if not ok:
            raise EnvironmentFailure(f"Command failed in {self.active}; see stage log")

    def stage(self, id, action):
        if self.run.get('controlled') and (self.run.get('_lease_lost') or self.run.get('stale')) and id not in {'report','github'}:
            raise EnvironmentFailure('Execution lease lost or version superseded; stopped at stage boundary')
        self.active = id
        stage = self.hub._stage(self.run, id)
        self.hub._start_stage(self.run, stage)
        try:
            action()
        except Exception:
            self.hub._complete_stage(self.run, stage, "failure")
            raise
        self.hub._complete_stage(self.run, stage, "success")

    def metadata(self):
        meta = self.hub._gh_json(["pr", "view", str(self.run["pr_number"]), "--repo", self.run["repo"],
                                 "--json", "state,title,headRefOid,baseRefOid,headRefName,baseRefName"])
        ref = self.hub._gh_json(["api", f"repos/{self.run['repo']}/git/ref/heads/{meta['baseRefName']}"])
        meta["baseRefOid"] = ref["object"]["sha"]
        return meta

    def resolve(self):
        meta = self.metadata()
        if meta["state"] != "OPEN":
            raise EnvironmentFailure("E2E acceptance requires an OPEN PR")
        if self.run.get('controlled') and (meta['headRefOid'] != self.run['expected_head'] or meta['baseRefOid'] != self.run['expected_base']):
            self.run['stale'] = True
            raise EnvironmentFailure('Queued PR version no longer matches GitHub; submit current version')
        self.run.update(title=meta["title"], head_sha=meta["headRefOid"], base_sha=meta["baseRefOid"],
                        head_ref=meta["headRefName"], base_ref=meta["baseRefName"], pr_state=meta["state"])
        self.log(json.dumps(meta, ensure_ascii=False, indent=2))
        self.save()
        self.publish("pending")
        if self.run.get('full_acceptance'):
            from review_policy import select
            from e2e_catalog import stages
            pages = self.hub._gh_json(['api', f"repos/{self.run['repo']}/pulls/{self.run['pr_number']}/files?per_page=100", '--paginate', '--slurp'])
            files = sorted({name for page in pages for file in page
                            for name in (file['filename'], file.get('previous_filename')) if name})
            policy = select(self.run['repo'], files, [s['id'] for s in self.run['suites']])
            self.run.update(policy=policy, changed_files=files, suites=policy['suites'])
            previous = {s['id']:s for s in self.run['stages']}
            self.run['stages'] = [previous.get(id, {'id':id,'name':name,'status':'queued','conclusion':None,
                'started_at':None,'finished_at':None,'duration_seconds':None}) for id,name in stages(policy['suites'])]
            self.save()
            if self.run.get('controlled') and policy['risky_files']:
                self.run['manual_approval_required'] = policy['risky_files']

    def publish(self, state):
        if self.run.get('controlled') and self.run.get('_lease_lost'):
            self.run['github'] = {'state':state,'ok':False,'error':'Execution lease lost; write suppressed'}
            self.save()
            return
        if self.run.get("diagnostic") or not self.run.get("head_sha"):
            self.run["github"] = {"state": "disabled", "reason": "diagnostic / unresolved PR"}
            self.save()
            return
        context = "newlink/e2e-local" if self.run["full_acceptance"] else "newlink/e2e-local-debug"
        try:
            # The share URL is read-only and intentionally contains no worker credential.
            result = self.hub._gh_json(["api", f"repos/{self.run['repo']}/statuses/{self.run['head_sha']}",
                "-f", f"state={state}", "-f", f"context={context}",
                "-f", f"description=Local E2E {state}; run {self.run['id']}"] +
                (["-f", 'target_url='+self.run['web_url']] if self.hub.public_base_url else []))
            self.run["github"] = {"state": state, "context": context, "id": result.get("id"), "ok": True}
        except Exception as exc:
            self.run["github"] = {"state": state, "context": context, "ok": False, "error": str(exc)}
            self.log(f"GitHub status write failed: {exc}")
        self.save()

    def preflight(self):
        if self.run.get('manual_approval_required'):
            raise EnvironmentFailure('High-risk build or installation changes require local approval before execution')
        if self.run.get('controlled') and self.run.get('review', {}).get('status') != 'completed':
            raise EnvironmentFailure('Real Agent review result missing; automatic execution remains blocked')
        result = self.stack.doctor()
        self.stack.output_json(self.artifacts / "preflight.json", result)
        self.run["preflight"] = result
        self.save()
        for check in result["checks"]:
            self.log(f"{'PASS' if check['ok'] else 'BLOCKED'} {check['name']}: {check['detail']}")
        if not result["ok"]:
            raise EnvironmentFailure(f"Environment preflight blocked: {sum(not c['ok'] for c in result['checks'])} missing inputs")

    def snapshot(self):
        lock = self.stack.snapshot(self.folder / "sources", self.run["preflight"]["revisions"])
        self.stack.output_json(self.artifacts / "sources.lock.json", lock)
        if not self.run.get('workspace') and not self.hub._prepare(self.run, "snapshot", {"head": self.run["head_sha"], "base": self.run["base_sha"]}):
            raise EnvironmentFailure("Cannot fetch frozen PR source; see snapshot log")
        workspace = Path(self.run["workspace"])
        # Existing local checkout is not an authoritative PR baseline.
        name = self.run["repo"].split("/")[1]
        baseline = self.folder / "baseline-source"
        self.command(["git", "clone", "--no-hardlinks", "--no-checkout", workspace, baseline], timeout=300)
        self.command(["git", "checkout", "--detach", self.run["base_sha"]], baseline, timeout=300)
        self.baseline_source = baseline
        if self.run.get("source_mode") == "pr-head":
            self.run["full_acceptance"] = False
            self.run["candidate_tree"] = self.stack.git(workspace, "rev-parse", "HEAD^{tree}")
            self.run["diagnostic_warning"] = "PR head only: target-branch changes are excluded; not merge acceptance"
            lock["candidate"] = {"repo": self.run["repo"], "head": self.run["head_sha"],
                                 "tree": self.run["candidate_tree"], "source_mode": "pr-head"}
            self.stack.output_json(self.artifacts / "sources.lock.json", lock)
            self.log(self.run["diagnostic_warning"])
            self.save()
            return
        try:
            self.command(["git", "-c", "user.name=Local E2E", "-c", "user.email=e2e@localhost",
                          "merge", "--no-commit", "--no-ff", self.run["base_sha"]], workspace, timeout=300)
        except EnvironmentFailure:
            conflicts = self.stack.git(workspace, "diff", "--name-only", "--diff-filter=U").splitlines()
            if conflicts:
                self.run["merge_conflicts"] = conflicts
                self.save()
                raise AssertionFailure("PR merge conflicts: " + ", ".join(conflicts))
            raise
        self.run["candidate_tree"] = self.stack.git(workspace, "write-tree")
        lock["candidate"] = {"repo": self.run["repo"], "head": self.run["head_sha"],
                              "base": self.run["base_sha"], "tree": self.run["candidate_tree"]}
        self.stack.output_json(self.artifacts / "sources.lock.json", lock)

    def build(self):
        self.images = {}
        provenance = {}
        for service, (name, variable, _) in self.stack.SERVICES.items():
            sha = self.run["base_sha"] if name == self.run["repo"].split("/")[1] else self.run["preflight"]["revisions"][name]
            image = f"local/pr-e2e-{service}:{sha[:12]}"
            record_path = self.stack.STATE / "build-contexts" / f"{name}-{sha[:12]}" / "build.json"
            record = json.loads(record_path.read_text()) if record_path.exists() else {}
            probe = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
                                   capture_output=True, text=True, timeout=30)
            if not (record.get("source_sha") == sha and record.get("exit_code") == 0
                    and probe.returncode == 0 and record.get("image_id") == probe.stdout.strip()):
                source = self.baseline_source if name == self.run["repo"].split("/")[1] else self.stack.ROOT / name
                self.command([sys.executable, self.stack.HERE / "build-service.py", service,
                              "--source", source, "--revision", sha], timeout=14400)
                record = json.loads(record_path.read_text())
            self.log(f"Verified CCE image {service}: {sha} {record['image_id']}")
            provenance[service] = record
            # Pin the immutable image ID, not a mutable tag.
            self.images[variable] = record["image_id"]
        self.stack.output_json(self.artifacts / "image-provenance.json", provenance)
        self.stack.output_json(self.artifacts / "images.json", self.images)
        self.env = self.stack.runtime_environment(self.folder / "private", self.images)
        self.env["COMPOSE_PROJECT_NAME"] = "newlink-e2e-" + self.run["id"]

    def compose(self, *args):
        self.command(["docker", "compose", "-f", self.stack.HERE / "compose.yaml", *args], env=self.env)

    def deploy(self):
        name = self.run["repo"].split("/")[1]
        service = next((s for s, (repo, _, _) in self.stack.SERVICES.items() if repo == name), None)
        if not service:
            raise EnvironmentFailure("PR repository is not registered in the integration baseline")
        image = f"local/pr-e2e-{service}:candidate-{self.run['id']}"
        self.command([sys.executable, self.stack.HERE / "build-service.py", service,
                      "--source", self.run["workspace"], "--revision", self.run["candidate_tree"],
                      "--image", image], timeout=14400)
        record = json.loads((self.stack.STATE / "build-contexts" /
                            f"{name}-{self.run['candidate_tree'][:12]}" / "build.json").read_text())
        self.stack.output_json(self.artifacts / "candidate-image.json", record)
        self.env[self.stack.SERVICES[service][1]] = record["image_id"]
        # Evidence is outside Docker volumes. Only this run's named project is removed.
        self.compose("down", "--volumes")
        self.compose("up", "-d", "--wait", "--wait-timeout", "300")
        self.command([sys.executable, self.stack.HERE / "bootstrap.py"], env=self.env, timeout=300)
        self.verify_services()

    def verify_services(self):
        self.command([sys.executable, self.stack.HERE / "bootstrap.py", "--check"], env=self.env, timeout=300)
        self.run["app_url"] = "http://localhost:18066"
        self.run["environment_status"] = "running"
        self.save()

    def baseline(self):
        # Release only explicitly owned test environments; preserve their volumes/evidence.
        self.command([sys.executable, self.stack.HERE / "local-stack.py", "stop"], timeout=300)
        for previous in self.hub.runs.values():
            if previous["id"] == self.run["id"] or previous.get("environment_status") != "running":
                continue
            project = "newlink-e2e-" + previous["id"]
            containers = subprocess.check_output(["docker", "ps", "-q", "--filter",
                           f"label=com.docker.compose.project={project}"], text=True, timeout=30).split()
            if containers:
                self.command(["docker", "stop", *containers], timeout=300)
            previous["environment_status"] = "stopped"
            self.hub._save(previous)
        self.compose("up", "-d", "--wait", "--wait-timeout", "300")
        self.command([sys.executable, self.stack.HERE / "bootstrap.py"], env=self.env, timeout=300)
        self.verify_services()
        selected = {suite["id"] for suite in self.run["suites"]}
        for suite in CORE:
            if suite not in selected:
                continue
            self.test_suite(suite, baseline=True)

    def test_suite(self, suite, baseline=False):
        directory = self.artifacts / ("baseline" if baseline else "candidate") / suite
        directory.mkdir(parents=True, exist_ok=True)
        harness = self.folder / "harness"
        if not harness.exists():
            shutil.copytree(self.stack.HERE / "playwright", harness,
                            ignore=shutil.ignore_patterns("node_modules", "results", "test-results"))
            (harness / "node_modules").symlink_to(self.stack.STATE / "playwright/node_modules", target_is_directory=True)
        env = {**(self.env or os.environ), "E2E_SETTINGS": os.environ.get('E2E_SETTINGS_FILE', str(self.stack.STATE / "settings.json")),
               "E2E_RUN_ID": self.run["id"], "E2E_SUITE": suite, "E2E_OUTPUT": str(directory),
               "E2E_APP_URL": "http://localhost:18066", "E2E_BASELINE": "1" if baseline else "0",
               "E2E_FAULT_CONTROL": str(self.stack.HERE / "fault-control.py")}
        try:
            self.command(["npx", "--no-install", "playwright", "test", "-c", "playwright.config.ts"],
                          harness, env, timeout=1200)
        except EnvironmentFailure:
            if (directory / "evidence.json").exists():
                raise AssertionFailure(f"{suite}: browser/integration assertion failed")
            raise
        file = directory / "evidence.json"
        if not file.exists():
            raise EnvironmentFailure(f"{suite}: reporter did not produce evidence.json")
        try:
            cases = validate_result(json.loads(file.read_text()), suite)
        except ValueError as exc:
            raise AssertionFailure(str(exc)) from exc
        if not baseline:
            self.run.setdefault("test_results", []).extend(cases)
            self.save()

    def report(self, verify=True):
        if verify and self.run.get("head_sha"):
            try:
                current = self.metadata()
                if (current["state"] != "OPEN" or current["headRefOid"] != self.run["head_sha"]
                        or current["baseRefOid"] != self.run["base_sha"]):
                    self.run["stale"] = True
                    self.failure_kind = "error"
                    self.run["error"] = "PR version changed; result is stale"
            except Exception as exc:
                self.run["error"] = f"Final version verification unavailable: {exc}"
                self.failure_kind = "error"
        evidence = {k: self.run.get(k) for k in ("id", "pr_url", "head_sha", "base_sha", "candidate_tree",
                    "suites", "full_acceptance", "test_results", "preflight", "error", "stale", "github", "merge_conflicts",
                    "source_mode", "diagnostic_warning")}
        self.stack.output_json(self.artifacts / "report.json", evidence)
        rows = "".join(f"<tr><td>{html.escape(s['name'])}</td><td>{html.escape(s['status'])}</td>"
                       f"<td>{html.escape(str(s.get('conclusion') or 'not executed'))}</td></tr>" for s in self.run["stages"])
        page = ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>E2E Evidence</title>"
                "<style>body{font:16px system-ui;margin:32px;max-width:1000px}td{padding:8px;border-bottom:1px solid #ddd}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>"
                f"<h1>{html.escape(self.run['id'])}</h1><p>Local test domain / real runtime. Not production NewLink certification.</p>"
                f"<table>{rows}</table><pre>{html.escape(json.dumps(evidence, ensure_ascii=False, indent=2))}</pre></html>")
        (self.artifacts / "report.html").write_text(page, encoding="utf-8")
        self.run["report_url"] = f"/artifacts/{self.run['id']}/report.html"
        self.save()

    def execute(self):
        import fcntl
        lock_path = self.stack.STATE / "environment.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a") as handle:
            # All Hub data directories share one fixed-port integration environment.
            fcntl.flock(handle, fcntl.LOCK_EX)
            self._execute_locked()

    def _execute_locked(self):
        from pr_pipeline_hub import utc_now
        self.run.update(status="running", started_at=utc_now(), test_results=[], environment_status="not_started")
        self.save()
        try:
            from local_agent_review import review
            for name, action in (("resolve", self.resolve), ("agent", lambda: review(self)), ("preflight", self.preflight),
                                 ("snapshot", self.snapshot), ("build", self.build),
                                 ("baseline", self.baseline), ("deploy", self.deploy)):
                self.stage(name, action)
            for suite in self.run["suites"]:
                self.stage(suite["id"], lambda s=suite["id"]: self.test_suite(s))
            self.failure_kind = "success"
        except Exception as exc:
            self.failure_kind = "failure" if isinstance(exc, AssertionFailure) and self.active != "baseline" else "error"
            if self.active == "baseline":
                self.run["baseline_issue"] = True
            self.run["error"] = str(exc)
            self.run["failure_stage"] = self.active
            self.log(f"ERROR [{self.failure_kind}]: {exc}")
            self.hub._skip_remaining(self.run, self.active)
        finally:
            try:
                self.stage("report", self.report)
            except Exception as exc:
                self.failure_kind = "error"
                self.run["error"] = f"Evidence finalization failed: {exc}"
            self.stage("github", lambda: self.publish(self.failure_kind))
            if not self.run.get("github", {}).get("ok") and not self.run.get("diagnostic"):
                self.hub._stage(self.run, "github")["conclusion"] = "failure"
            self.run["failure_kind"] = self.failure_kind
            self.hub._finish(self.run, "success" if self.failure_kind == "success" else "failure",
                ("PR head 诊断通过（不证明可合入）" if self.run.get("source_mode") == "pr-head" else
                 "真实 E2E 执行集合通过") if self.failure_kind == "success" else
                f"{'用例失败' if self.failure_kind == 'failure' else '环境或证据阻塞'}：{self.run.get('error', '')}")
            try:
                self.report(verify=False)
            except Exception as exc:
                self.log(f"Final report render failed: {exc}")
