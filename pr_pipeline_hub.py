#!/usr/bin/env python3
"""Small PR pipeline server intended to run inside WSL."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import queue
import re
import secrets
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from e2e_catalog import CATALOG, select_suites, stages as e2e_stages


PR_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/pull/(?P<number>[1-9][0-9]*)/?$"
)
SECRET_PATTERNS = (
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,255}\b"),
    re.compile(r"(?i)(authorization\s*:\s*(?:bearer|basic)\s+)[^\s]+"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_pr_url(value: str) -> tuple[str, str, int]:
    match = PR_URL_RE.fullmatch(value.strip())
    if not match:
        raise ValueError("仅支持 https://github.com/<owner>/<repo>/pull/<number> 格式")
    return match.group("owner"), match.group("repo"), int(match.group("number"))


def redact(value: str) -> str:
    result = value
    result = SECRET_PATTERNS[0].sub("[REDACTED GITHUB TOKEN]", result)
    result = SECRET_PATTERNS[1].sub(r"\1[REDACTED]", result)
    return result


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def command_text(argv: list[str]) -> str:
    return " ".join(json.dumps(item, ensure_ascii=False) if any(ch.isspace() for ch in item) else item for item in argv)


class PipelineHub:
    STAGES = (
        ("prepare", "准备代码", 300),
        ("merge", "合并预演", 300),
        ("format", "变更格式", 180),
        ("vet", "静态检查", 900),
        ("unit", "单元测试", 1800),
        ("docs", "文档检查", 300),
    )

    def __init__(self, data_dir: Path, public_base_url: str = "") -> None:
        self.data_dir = data_dir
        self.public_base_url = public_base_url.rstrip("/")
        self.embed_view_token = os.environ.get("PIPELINE_EMBED_VIEW_TOKEN", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        self.runs_dir = data_dir / "runs"
        self.repos_dir = data_dir / "repos"
        self.workspaces_dir = data_dir / "workspaces"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.repos_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
        configured = os.environ.get("PIPELINE_ALLOWED_REPOS", "rollingfruit/agent-governance-gw")
        self.allowed_repos = {item.strip().lower() for item in configured.split(",") if item.strip()}
        self.gh_cli = self._find_gh_cli()
        self.git_cli = self._find_git_cli()
        self.windows_proxy = self._find_windows_proxy() if self.git_cli.lower().endswith(".exe") else ""
        self.lock = threading.RLock()
        self.queue: queue.Queue[str] = queue.Queue()
        self.runs: dict[str, dict] = {}
        self._load_runs()
        self.external_control = os.environ.get('PIPELINE_CONTROL_MODE') == 'ecs'
        if self.external_control:
            from control_worker import work
            self.worker = threading.Thread(target=work, args=(self,), name='ecs-worker', daemon=True)
        else:
            self.worker = threading.Thread(target=self._worker, name="pipeline-worker", daemon=True)
        if os.environ.get('PIPELINE_NO_WORKER') != '1':
            self.worker.start()

    def _run_web_url(self, base_url: str, run_id: str) -> str:
        url = f"{base_url.rstrip('/')}/runs/{run_id}"
        view_token = os.environ.get("PIPELINE_SHARE_TOKEN", os.environ.get("PIPELINE_VIEW_TOKEN", "")).strip()
        if self.embed_view_token and view_token:
            return f"{url}?{urlencode({'access_token': view_token})}"
        return url

    def _find_gh_cli(self) -> str:
        configured = os.environ.get("PIPELINE_GH_CLI", "").strip()
        if configured:
            return configured
        native = shutil.which("gh")
        if native:
            return native
        windows_candidates = sorted(
            Path("/mnt/c/Users").glob("*/AppData/Local/Programs/GitHub CLI/gh.exe")
        )
        if windows_candidates:
            return str(windows_candidates[0])
        raise RuntimeError("未找到 GitHub CLI，请设置 PIPELINE_GH_CLI")

    @staticmethod
    def _find_git_cli() -> str:
        configured = os.environ.get("PIPELINE_GIT_CLI", "").strip()
        if configured:
            return configured
        native = shutil.which("git")
        if native:
            return native
        windows_git = Path("/mnt/c/Program Files/Git/cmd/git.exe")
        if windows_git.exists():
            return str(windows_git)
        raise RuntimeError("未找到 Git CLI，请设置 PIPELINE_GIT_CLI")

    @staticmethod
    def _find_windows_proxy() -> str:
        configured = os.environ.get("PIPELINE_WINDOWS_PROXY", "").strip()
        if configured:
            return configured if "://" in configured else f"http://{configured}"
        powershell = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
        if not powershell.exists():
            return ""
        script = (
            "$s=Get-ItemProperty -LiteralPath "
            "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings';"
            "if($s.ProxyEnable -eq 1){$s.ProxyServer}"
        )
        result = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        value = result.stdout.strip()
        if not value:
            return ""
        return value if "://" in value else f"http://{value}"

    def _load_runs(self) -> None:
        for path in sorted(self.runs_dir.glob("*/run.json")):
            try:
                run = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if run.get("status") == "running":
                run["status"] = "interrupted"
                run["conclusion"] = "failure"
                run["finished_at"] = utc_now()
                run["summary"] = "流水线服务重启，原运行已中断"
                atomic_json(path, run)
            self.runs[run["id"]] = run
        for run in sorted(self.runs.values(), key=lambda r: (r.get("enqueue_order", 0), r["created_at"], r["id"])):
            if run.get("status") == "queued":
                self.queue.put(run["id"])

    def create_run(self, pr_url: str, requested_by: str, request_base_url: str,
                   profile: str = "code-review", suites=None, diagnostic: bool = False,
                   request_id: str = "", source_mode: str = "merge", _control_run=None) -> dict:
        if self.external_control and _control_run is None:
            from control_worker import submit
            return submit(self, pr_url, requested_by, profile, suites, diagnostic, request_id, source_mode)
        if not isinstance(request_id, str) or len(request_id) > 256:
            raise ValueError("Invalid request_id")
        if not isinstance(source_mode, str) or source_mode not in {"merge", "pr-head"}:
            raise ValueError("Invalid source_mode")
        if source_mode == "pr-head" and (profile != "browser-e2e" or not diagnostic):
            raise ValueError("pr-head requires a diagnostic browser-e2e run; it cannot certify merge readiness")
        artifact = bool(_control_run and _control_run.get('source_mode') == 'artifact')
        if artifact:
            owner, repo = _control_run['repo'].split('/')
            number = None
            pr_url = ''
        else:
            owner, repo, number = parse_pr_url(pr_url)
        repo_full_name = f"{owner}/{repo}"
        if repo_full_name.lower() not in self.allowed_repos and not (_control_run and _control_run.get('kind')=='batch'):
            raise PermissionError(f"仓库 {repo_full_name} 不在 PIPELINE_ALLOWED_REPOS 中")
        if profile not in {"code-review", "browser-e2e"}:
            raise ValueError("Unknown pipeline profile")
        selected, full = select_suites(repo_full_name, number, suites) if profile == "browser-e2e" else ([], False)
        if source_mode == "pr-head":
            full = False
        definitions = [(i, n, 1200) for i, n in e2e_stages(selected)] if selected else self.STAGES
        run_id = _control_run['id'] if _control_run else datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        stages = [
            {
                "id": stage_id,
                "name": name,
                "status": "queued",
                "conclusion": None,
                "started_at": None,
                "finished_at": None,
                "duration_seconds": None,
            }
            for stage_id, name, _ in definitions
        ]
        base_url = self.public_base_url or request_base_url.rstrip("/")
        run = {
            "id": run_id,
            "pr_url": pr_url.strip(),
            "repo": repo_full_name,
            "pr_number": number,
            "pr_state": None,
            "title": f"PR #{number}",
            "head_ref": None,
            "head_sha": None,
            "base_ref": None,
            "base_sha": None,
            "requested_by": requested_by.strip() or "group-chat",
            "status": "queued",
            "conclusion": None,
            "created_at": utc_now(),
            "started_at": None,
            "finished_at": None,
            "duration_seconds": None,
            "summary": "等待 Runner",
            "web_url": self._run_web_url(base_url, run_id),
            "workspace": None,
            "stages": stages,
            "profile": profile,
            "suites": selected,
            "full_acceptance": full,
            "diagnostic": diagnostic,
            "request_id": request_id,
            "source_mode": source_mode,
        }
        with self.lock:
            if request_id:
                previous = next((r for r in self.runs.values() if r.get("request_id") == request_id), None)
                if previous:
                    if previous.get("source_mode", "merge") != source_mode:
                        raise ValueError("request_id already used for a different source mode")
                    if (previous["pr_url"], previous["profile"], previous["suites"], previous["diagnostic"]) != (
                            run["pr_url"], profile, selected, diagnostic):
                        raise ValueError("request_id already used for a different submission")
                    return self.public_run(previous)
            self.runs[run_id] = run
            run["enqueue_order"] = max((r.get("enqueue_order", 0) for r in self.runs.values()), default=0) + 1
            self._save(run)
            if _control_run:
                run.update(controlled=True, expected_head=_control_run['head_sha'], expected_base=_control_run['base_sha'])
                self._save(run)
            else:
                self.queue.put(run_id)
        return self.public_run(run)

    def list_runs(self) -> list[dict]:
        with self.lock:
            values = sorted(self.runs.values(), key=lambda item: item["created_at"], reverse=True)
            return [self.public_run(item) for item in values[:100]]

    def get_run(self, run_id: str) -> dict | None:
        with self.lock:
            value = self.runs.get(run_id)
            return self.public_run(value) if value else None

    def public_run(self, run: dict) -> dict:
        value = dict(run)
        value["local_url"] = f"{os.environ.get('PIPELINE_LOCAL_BASE_URL', 'http://127.0.0.1:8788')}/runs/{run['id']}"
        if self.public_base_url:
            value["web_url"] = self._run_web_url(self.public_base_url, run["id"])
        publication = self.runs_dir / run["id"] / "publication.json"
        if publication.is_file():
            try:
                value["publication"] = json.loads(publication.read_text())
            except (OSError, json.JSONDecodeError):
                pass
        value.pop("workspace", None)
        value.pop("request_id", None)
        pending = sorted((r for r in self.runs.values() if r.get("status") == "queued"),
                         key=lambda r: (r.get("enqueue_order", 0), r["created_at"], r["id"]))
        value["queue_position"] = next((i + 1 for i, r in enumerate(pending) if r["id"] == run["id"]), 0)
        if run.get("profile") == "browser-e2e":
            value["steps"] = []
            root = self.runs_dir / run["id"] / "artifacts"
            value["test_reports"] = [
                {"phase": file.relative_to(root).parts[0], "suite": file.relative_to(root).parts[1],
                 "url": f"/artifacts/{run['id']}/{file.relative_to(root).as_posix()}"}
                for file in sorted(root.glob("*/*/html/index.html"))
            ]
            for file in sorted(root.glob("*/*/progress.ndjson")):
                try:
                    with file.open("rb") as handle:
                        handle.seek(0, os.SEEK_END)
                        handle.seek(max(0, handle.tell() - 32000))
                        lines = handle.read().decode("utf-8", errors="replace").splitlines()
                    for line in lines:
                        try:
                            value["steps"].append({**json.loads(line), "phase": file.relative_to(root).parts[0],
                                                   "suite": file.relative_to(root).parts[1]})
                        except json.JSONDecodeError:
                            pass
                except OSError:
                    continue
        return value

    def read_log(self, run_id: str, stage_id: str, limit: int = 256_000) -> str | None:
        with self.lock:
            if run_id not in self.runs:
                return None
            if stage_id not in {item["id"] for item in self.runs[run_id]["stages"]}:
                return None
        path = self.runs_dir / run_id / f"{stage_id}.log"
        if not path.exists():
            return ""
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            return handle.read().decode("utf-8", errors="replace")

    def _save(self, run: dict) -> None:
        atomic_json(self.runs_dir / run["id"] / "run.json", run)

    def _worker(self) -> None:
        while True:
            run_id = self.queue.get()
            try:
                self._execute(run_id)
            except Exception as exc:  # Keep the worker alive after infrastructure errors.
                self._fail_run(run_id, f"Runner 内部错误：{redact(str(exc))}")
            finally:
                self.queue.task_done()

    def _execute(self, run_id: str) -> None:
        if self.runs[run_id].get('kind')=='batch':
            if self.runs[run_id].get('source_mode')=='artifact':
                from artifact_runner import ArtifactRunner
                ArtifactRunner(self,self.runs[run_id]).execute()
            else:
                from batch_runner import BatchRunner
                BatchRunner(self,self.runs[run_id]).execute()
            return
        if self.runs[run_id].get("profile") == "browser-e2e":
            from e2e_runner import E2ERunner
            E2ERunner(self, self.runs[run_id]).execute()
            return
        with self.lock:
            run = self.runs[run_id]
            run["status"] = "running"
            run["started_at"] = utc_now()
            run["summary"] = "正在准备 PR 代码"
            self._save(run)

        if not self._prepare(run):
            self._skip_remaining(run, "prepare")
            self._finish(run, "failure", "准备代码失败")
            return

        workspace = Path(run["workspace"])
        base_sha = run["base_sha"]
        go_env = os.environ.copy()
        home = Path.home()
        go_paths = [home / ".local/go/bin", Path("/usr/local/go/bin")]
        go_env["PATH"] = ":".join(str(path) for path in go_paths) + ":" + go_env.get("PATH", "")
        go_env["GOTOOLCHAIN"] = self._go_toolchain(workspace) or go_env.get("GOTOOLCHAIN", "auto")
        if os.environ.get("PIPELINE_GOPROXY"):
            go_env["GOPROXY"] = os.environ["PIPELINE_GOPROXY"]
        go_env["PIPELINE_BASE_SHA"] = base_sha
        go_files_cmd = (
            'files=$(git diff --name-only --diff-filter=ACMR "$PIPELINE_BASE_SHA"...HEAD -- "*.go"); '
            'unformatted=""; '
            'if test -n "$files"; then unformatted=$(gofmt -l $files); fi; '
            'if test -n "$unformatted"; then '
            'printf "以下文件需要执行 gofmt:\\n%s\\n" "$unformatted"; exit 1; fi'
        )
        commands = {
            "merge": ["git", "merge", "--no-commit", "--no-ff", base_sha],
            "format": ["bash", "-lc", go_files_cmd],
            "vet": ["go", "vet", "./..."],
            "unit": ["go", "test", "./..."],
            "docs": ["bash", "scripts/verify-change-docs.sh", base_sha],
        }
        merge_timeout = next(timeout for stage_id, _, timeout in self.STAGES if stage_id == "merge")
        if not self._command_stage(run, "merge", commands["merge"], workspace, go_env, merge_timeout):
            self._skip_remaining(run, "merge")
            self._finish(run, "failure", "合并预演失败，PR 与最新基线存在冲突")
            return

        failures = []
        for stage_id, _, timeout in self.STAGES[2:]:
            if not self._command_stage(run, stage_id, commands[stage_id], workspace, go_env, timeout):
                failures.append(self._stage(run, stage_id)["name"])
        if failures:
            self._finish(run, "failure", f"{', '.join(failures)}失败，Agent 可进入日志继续排查")
        else:
            self._finish(run, "success", "当前支持的本地质量门禁全部通过")

    @staticmethod
    def _go_toolchain(workspace: Path) -> str:
        go_mod = workspace / "go.mod"
        if not go_mod.exists():
            return ""
        for line in go_mod.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] == "toolchain" and parts[1].startswith("go"):
                return parts[1]
        return ""

    def _prepare(self, run: dict, stage_id: str = "prepare", frozen: dict | None = None) -> bool:
        stage = self._stage(run, stage_id)
        self._start_stage(run, stage)
        log_path = self.runs_dir / run["id"] / f"{stage_id}.log"
        try:
            metadata = self._gh_json(
                [
                    "pr", "view", str(run["pr_number"]), "--repo", run["repo"],
                    "--json", "number,title,headRefName,headRefOid,baseRefName,baseRefOid,url,state,commits",
                ]
            )
            pr_state = str(metadata.get("state", "")).upper()
            if frozen and (metadata["headRefOid"] != frozen["head"] or pr_state != "OPEN"):
                raise RuntimeError("PR changed after submission; resubmit the E2E run")
            if pr_state not in {"OPEN", "MERGED"}:
                raise RuntimeError(f"PR 状态为 {pr_state or 'UNKNOWN'}，只运行开放或已合入 PR")
            token = self._github_token()
            git_env = self._git_env(token)
            mirror = self.repos_dir / run["repo"].lower().replace("/", "--")
            workspace = self.workspaces_dir / run["id"]
            mirror_arg = self._git_path(mirror)
            clone_url = f"https://github.com/{run['repo']}.git"
            lines = [
                f"PR: {metadata['url']}",
                f"状态: {pr_state}",
                f"标题: {metadata['title']}",
                f"提交: {metadata['headRefOid']}",
                f"基线: {metadata['baseRefName']}@{metadata['baseRefOid']}",
            ]
            if not mirror.exists():
                lines.append(f"创建镜像缓存: {mirror}")
                self._checked([self.git_cli, "clone", "--mirror", clone_url, mirror_arg], git_env, log_path, lines, attempts=3)
            else:
                lines.append(f"复用镜像缓存: {mirror}")
            fetch_refspecs = [
                f"+refs/heads/{metadata['baseRefName']}:refs/heads/{metadata['baseRefName']}",
                f"+refs/pull/{run['pr_number']}/head:refs/pull/{run['pr_number']}/head",
            ]
            self._checked(
                [self.git_cli, "--git-dir", mirror_arg, "fetch", "--prune", "origin", *fetch_refspecs],
                git_env,
                log_path,
                lines,
                attempts=3,
            )
            if pr_state == "MERGED":
                commits = metadata.get("commits") or []
                first_commit = str(commits[0].get("oid", "")) if commits else ""
                if not first_commit:
                    raise RuntimeError("已合入 PR 缺少提交列表，无法还原检视基线")
                base_sha = self._capture(["git", "--git-dir", str(mirror), "rev-parse", f"{first_commit}^"])
                lines.append(f"事后检视基线: 首个 PR 提交的父提交 @{base_sha}")
            else:
                base_sha = self._capture(["git", "--git-dir", str(mirror), "rev-parse", f"refs/heads/{metadata['baseRefName']}"])
                lines.append(f"最新基线: {metadata['baseRefName']}@{base_sha}")
            self._checked(
                ["git", "--git-dir", str(mirror), "worktree", "add", "--detach", str(workspace), f"refs/pull/{run['pr_number']}/head"],
                git_env,
                log_path,
                lines,
            )
            if frozen and (base_sha != frozen["base"] or self._capture(["git", "-C", str(workspace), "rev-parse", "HEAD"]) != frozen["head"]):
                raise RuntimeError("Fetched refs differ from frozen E2E SHA; resubmit")
            lines.append(f"隔离工作区: {workspace}")
            log_path.write_text("\n".join(redact(line) for line in lines) + "\n", encoding="utf-8")
            with self.lock:
                run.update(
                    {
                        "title": metadata["title"],
                        "pr_state": pr_state,
                        "head_ref": metadata["headRefName"],
                        "head_sha": metadata["headRefOid"],
                        "base_ref": metadata["baseRefName"],
                        "base_sha": base_sha,
                        "workspace": str(workspace),
                        "summary": "代码准备完成，开始质量检查",
                    }
                )
                self._complete_stage(run, stage, "success")
            return True
        except Exception as exc:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write("\nERROR: " + redact(str(exc)) + "\n")
            with self.lock:
                self._complete_stage(run, stage, "failure")
            return False

    def _checked(
        self,
        argv: list[str],
        env: dict[str, str],
        log_path: Path,
        lines: list[str],
        attempts: int = 1,
    ) -> None:
        for attempt in range(1, attempts + 1):
            lines.append("$ " + command_text(argv))
            result = subprocess.run(argv, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
            if result.stdout:
                lines.extend(result.stdout.rstrip().splitlines())
            if result.returncode == 0:
                return
            if attempt < attempts:
                delay = attempt * 2
                lines.append(f"网络操作失败，{delay} 秒后重试（{attempt}/{attempts}）")
                log_path.write_text("\n".join(redact(line) for line in lines) + "\n", encoding="utf-8")
                time.sleep(delay)
        log_path.write_text("\n".join(redact(line) for line in lines) + "\n", encoding="utf-8")
        raise RuntimeError(f"命令退出码 {result.returncode}: {command_text(argv)}")

    @staticmethod
    def _capture(argv: list[str]) -> str:
        result = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"命令退出码 {result.returncode}: {command_text(argv)}")
        return result.stdout.strip()

    def _command_stage(
        self,
        run: dict,
        stage_id: str,
        argv: list[str],
        workspace: Path,
        env: dict[str, str],
        timeout: int,
        manage_stage: bool = True,
        append: bool = False,
    ) -> bool:
        stage = self._stage(run, stage_id)
        if manage_stage:
            self._start_stage(run, stage)
        log_path = self.runs_dir / run["id"] / f"{stage_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        process = subprocess.Popen(
            argv,
            cwd=workspace,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        output_queue: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                output_queue.put(line)
            output_queue.put(None)

        threading.Thread(target=read_output, daemon=True).start()
        timed_out = False
        stream_closed = False
        with log_path.open("a" if append else "w", encoding="utf-8") as handle:
            handle.write(f"$ {command_text(argv)}\n\n")
            handle.flush()
            while process.poll() is None or not stream_closed:
                try:
                    line = output_queue.get(timeout=0.2)
                    if line is None:
                        stream_closed = True
                    else:
                        handle.write(redact(line))
                        handle.flush()
                except queue.Empty:
                    pass
                if not timed_out and time.monotonic() - started > timeout:
                    timed_out = True
                    os.killpg(process.pid, signal.SIGTERM)
                    handle.write(f"\nERROR: 阶段超过 {timeout} 秒，已终止\n")
                    handle.flush()
                if timed_out and process.poll() is None and time.monotonic() - started > timeout + 5:
                    os.killpg(process.pid, signal.SIGKILL)
            return_code = process.wait()
            if timed_out:
                return_code = 124
            handle.write(f"\n[exit code: {return_code}]\n")
        if manage_stage:
            with self.lock:
                self._complete_stage(run, stage, "success" if return_code == 0 else "failure")
        return return_code == 0

    def _gh_json(self, args: list[str]) -> dict:
        result = subprocess.run(
            [self.gh_cli, *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(redact(result.stderr.strip() or "GitHub CLI 请求失败"))
        return json.loads(result.stdout)

    def _github_token(self) -> str:
        result = subprocess.run(
            [self.gh_cli, "auth", "token"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError("GitHub CLI 尚未登录，请先执行 gh auth login --web")
        return result.stdout.strip()

    def _git_env(self, token: str) -> dict[str, str]:
        value = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env = os.environ.copy()
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
        env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: basic {value}"
        env["GIT_TERMINAL_PROMPT"] = "0"
        if self.windows_proxy:
            env["HTTP_PROXY"] = self.windows_proxy
            env["HTTPS_PROXY"] = self.windows_proxy
            env["http_proxy"] = self.windows_proxy
            env["https_proxy"] = self.windows_proxy
        return env

    def _git_path(self, path: Path) -> str:
        if not self.git_cli.lower().endswith(".exe"):
            return str(path)
        result = subprocess.run(
            ["wslpath", "-w", str(path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"无法转换路径: {path}")
        return result.stdout.strip()

    def _stage(self, run: dict, stage_id: str) -> dict:
        return next(stage for stage in run["stages"] if stage["id"] == stage_id)

    def _start_stage(self, run: dict, stage: dict) -> None:
        with self.lock:
            stage["status"] = "running"
            stage["started_at"] = utc_now()
            run["summary"] = f"正在执行：{stage['name']}"
            self._save(run)

    def _complete_stage(self, run: dict, stage: dict, conclusion: str) -> None:
        stage["status"] = "completed"
        stage["conclusion"] = conclusion
        stage["finished_at"] = utc_now()
        stage["duration_seconds"] = self._duration(stage["started_at"], stage["finished_at"])
        self._save(run)

    def _skip_remaining(self, run: dict, failed_stage_id: str) -> None:
        found = False
        with self.lock:
            for stage in run["stages"]:
                if stage["id"] == failed_stage_id:
                    found = True
                    continue
                if found and stage["status"] == "queued":
                    stage["status"] = "completed"
                    stage["conclusion"] = "skipped"
                    stage["finished_at"] = utc_now()
            self._save(run)

    def _finish(self, run: dict, conclusion: str, summary: str) -> None:
        with self.lock:
            run["status"] = "completed"
            run["conclusion"] = conclusion
            run["finished_at"] = utc_now()
            run["duration_seconds"] = self._duration(run["started_at"], run["finished_at"])
            run["summary"] = summary
            self._save(run)

    def _fail_run(self, run_id: str, message: str) -> None:
        with self.lock:
            run = self.runs.get(run_id)
            if not run:
                return
            run["status"] = "completed"
            run["conclusion"] = "failure"
            run["finished_at"] = utc_now()
            run["summary"] = message
            self._save(run)

    @staticmethod
    def _duration(started_at: str | None, finished_at: str | None) -> int | None:
        if not started_at or not finished_at:
            return None
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finish = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        return max(0, round((finish - start).total_seconds()))


class PipelineRequestHandler(BaseHTTPRequestHandler):
    server_version = "PRPipelineHub/0.1"

    @property
    def hub(self) -> PipelineHub:
        return self.server.hub  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/health":
            share_health = None
            health_file = self.hub.data_dir / 'share-health.json'
            if health_file.is_file():
                try:
                    share_health = json.loads(health_file.read_text())
                except (OSError, json.JSONDecodeError):
                    pass
            self._json(
                {
                    "status": "ok",
                    "runner": os.environ.get("PIPELINE_RUNNER_NAME", "Local WSL"),
                    "time": utc_now(),
                    "public_base_url": self.hub.public_base_url,
                    "shareable_links": bool(self.hub.public_base_url) and (share_health or {}).get('reachable', not bool(os.environ.get('PIPELINE_SHARE_TOKEN'))),
                    "sharing": share_health,
                    "profiles": ["code-review", "browser-e2e"],
                    "allowed_repos": sorted(self.hub.allowed_repos),
                }
            )
            return
        if path.startswith("/api/") and not self._view_authorized(parsed.query):
            self._error(HTTPStatus.UNAUTHORIZED, "查看令牌无效")
            return
        if path == "/api/runs":
            self._json({"runs": self.hub.list_runs()})
            return
        if path == "/api/e2e/suites":
            self._json({"suites": CATALOG})
            return
        if path.startswith("/artifacts/"):
            if not self._view_authorized(parsed.query):
                self._error(HTTPStatus.UNAUTHORIZED, "查看令牌无效")
                return
            parts = path.split("/", 3)
            if len(parts) != 4 or not re.fullmatch(r"[A-Za-z0-9-]+", parts[2]):
                self._error(HTTPStatus.NOT_FOUND, "报告不存在")
                return
            root = (self.hub.runs_dir / parts[2] / "artifacts").resolve()
            file = (root / parts[3]).resolve()
            if not file.is_relative_to(root) or not file.is_file():
                self._error(HTTPStatus.NOT_FOUND, "报告不存在")
                return
            data = file.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        match = re.fullmatch(r"/api/runs/([A-Za-z0-9-]+)", path)
        if match:
            run = self.hub.get_run(match.group(1))
            if not run:
                self._error(HTTPStatus.NOT_FOUND, "运行不存在")
            else:
                self._json(run)
            return
        match = re.fullmatch(r"/api/runs/([A-Za-z0-9-]+)/stages/([A-Za-z0-9-]+)/log", path)
        if match:
            content = self.hub.read_log(match.group(1), match.group(2))
            if content is None:
                self._error(HTTPStatus.NOT_FOUND, "日志不存在")
            else:
                self._text(content, "text/plain; charset=utf-8")
            return
        if path.startswith("/runs/") or path == "/":
            self._static("index.html", "text/html; charset=utf-8")
            return
        if path == "/app.js":
            self._static("app.js", "text/javascript; charset=utf-8")
            return
        if path == "/styles.css":
            self._static("styles.css", "text/css; charset=utf-8")
            return
        self._error(HTTPStatus.NOT_FOUND, "页面不存在")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/runs":
            self._error(HTTPStatus.NOT_FOUND, "接口不存在")
            return
        if not self._trigger_authorized():
            self._error(HTTPStatus.UNAUTHORIZED, "触发令牌无效")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 64_000:
                raise ValueError("请求体大小无效")
            body = json.loads(self.rfile.read(length))
            pr_url = str(body.get("pr_url", ""))
            requested_by = str(body.get("requested_by", "group-chat"))
            request_base_url = f"http://{self.headers.get('Host', '127.0.0.1')}"
            profile = body.get("profile", "code-review")
            diagnostic = body.get("diagnostic", False)
            if not isinstance(profile, str) or not isinstance(diagnostic, bool):
                raise ValueError("Invalid profile or diagnostic value")
            run = self.hub.create_run(pr_url, requested_by, request_base_url, profile, body.get("suites"), diagnostic,
                                      body.get("request_id", ""), body.get("source_mode", "merge"))
            self._json(run, HTTPStatus.ACCEPTED)
        except PermissionError as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
        except (ValueError, json.JSONDecodeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, redact(str(exc)))

    def _view_authorized(self, query: str) -> bool:
        expected = os.environ.get("PIPELINE_VIEW_TOKEN", "")
        if not expected:
            return True
        supplied = self.headers.get("X-Pipeline-View-Token", "")
        if not supplied:
            supplied = parse_qs(query).get("access_token", [""])[0]
        return secrets.compare_digest(expected, supplied)

    def _trigger_authorized(self) -> bool:
        expected = os.environ.get("PIPELINE_TRIGGER_TOKEN", "")
        if not expected:
            return True
        supplied = self.headers.get("X-Pipeline-Token", "")
        return secrets.compare_digest(expected, supplied)

    def _static(self, name: str, content_type: str) -> None:
        path = Path(__file__).resolve().parent / "static" / name
        if not path.exists():
            self._error(HTTPStatus.NOT_FOUND, "静态文件不存在")
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _text(self, value: str, content_type: str) -> None:
        data = value.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json({"error": message}, status)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} [{utc_now()}] {fmt % args}")


class PipelineHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], hub: PipelineHub) -> None:
        super().__init__(address, PipelineRequestHandler)
        self.hub = hub


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the WSL PR Pipeline Hub")
    parser.add_argument("--host", default=os.environ.get("PIPELINE_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PIPELINE_PORT", "8787")))
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("PIPELINE_DATA_DIR", Path.home() / ".local/share/pr-pipeline-hub")),
    )
    args = parser.parse_args()
    hub = PipelineHub(args.data_dir, os.environ.get("PIPELINE_PUBLIC_BASE_URL", ""))
    server = PipelineHTTPServer((args.host, args.port), hub)
    print(f"PR Pipeline Hub listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
