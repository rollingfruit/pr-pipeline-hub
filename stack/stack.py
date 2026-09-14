#!/usr/bin/env python3
"""Local-only CCE stack inputs. Never source a developer/production deploy.env."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tarfile
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("E2E_WORKSPACE_ROOT", HERE.parent.parent))
STATE = Path(os.environ.get("E2E_STATE_DIR", Path.home() / ".local/share/newlink-pr-e2e"))
SERVICES = {
    "mattermost": ("mattermost", "MATTERMOST_IMAGE", 8066),
    "multica-server": ("multica-aiwelink", "MULTICA_IMAGE", 8080),
    "agentlink": ("AgentLink", "AGENTLINK_IMAGE", 8643),
    "governance": ("agent-governance-gw", "GOVERNANCE_IMAGE", 8684),
    "gateway": ("semantic-gateway", "GATEWAY_IMAGE", 8081),
    "schedule": ("semantic-schedule", "SCHEDULE_IMAGE", 8766),
    "gmagent": ("gmagent", "GMAGENT_IMAGE", 3030),
    "skills-market": ("skills-market", "SKILLS_IMAGE", 8683),
    "cellmem": ("CellMem", "CELLMEM_IMAGE", 8096),
    "temporal": ("aiwelink-temporal", "TEMPORAL_IMAGE", 7233),
    "router": ("service_router", "ROUTER_IMAGE", 80),
}
SOURCE_REPOS = [value[0] for value in SERVICES.values()] + ["public-service"]


def output_json(path, value, private=False):
    path = Path(path)
    frozen = os.environ.get('E2E_FROZEN_SETTINGS')
    if frozen and path.resolve() == Path(frozen).resolve():
        expected = json.loads(path.read_text())
        # Reconnection clears this projection temporarily; the frozen binding remains authoritative.
        comparable = lambda data: {k: v for k, v in data.items() if k != 'RUNTIME_ID'}
        if comparable(value) != comparable(expected):
            raise RuntimeError('Frozen test settings cannot be changed during execution')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    if private:
        temp.chmod(0o600)
    temp.replace(path)


def config():
    path = Path(os.environ.get("E2E_SETTINGS_FILE", STATE / "settings.json"))
    if not path.exists():
        defaults = json.loads((HERE / "environment.example.json").read_text())
        defaults["TEST_ADMIN_PASSWORD"] = secrets.token_urlsafe(24)
        defaults["CODEX_HOME"] = str(STATE / "codex-home")
        defaults["TEST_WORKSPACE"] = str(STATE / "agent-workspace")
        output_json(path, defaults, private=True)
    return json.loads(path.read_text())


def capture(argv, timeout=30):
    result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{argv[0]} failed: {result.stderr[-1200:]}")
    return result.stdout.strip()


def git(repo, *args):
    return capture(["git", "-c", f"safe.directory={repo}", "-C", str(repo), *args])


def required_assets(repo):
    if repo.name == "public-service":
        return ["deps/Python-3.11.15.tgz"]
    dockerfile = repo / "Dockerfile"
    if not dockerfile.exists():
        return ["Dockerfile"]
    contents = dockerfile.read_text(encoding="utf-8", errors="replace")
    paths = set(re.findall(r"(?:source=|COPY\s+)([\w./-]+\.(?:tar\.gz|tgz|zip))", contents))
    if repo.name == "mattermost":
        paths.update(("build/deploy/installers/mattermost-go-mod-cache.tar.gz",
                      "build/deploy/installers/mattermost-webapp-npm-cache.tar.gz"))
    if repo.name == "AgentLink":
        paths.add("build/deploy/assets/cloud-desktop-sdk")
    return sorted(paths)


def asset_path(repo, relative):
    local = repo / relative
    cached = STATE / "build-inputs" / Path(relative).name
    return cached if cached.is_file() else local


def doctor(include_runtime=True):
    cfg = config()
    checks = []
    def add(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
    for program in ("docker", "git", "node", "npm"):
        add(program, shutil.which(program), "installed" if shutil.which(program) else "not installed in WSL")
    try:
        add("docker-engine", True, capture(["docker", "info", "--format", "{{.ServerVersion}}"], 15))
        add("compose", True, capture(["docker", "compose", "version"], 15))
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        add("docker-engine", False, str(exc))
    revisions = {}
    for name in SOURCE_REPOS:
        repo = ROOT / name
        try:
            revisions[name] = git(repo, "rev-parse", "HEAD")
            add(f"source:{name}", True, revisions[name])
        except (RuntimeError, OSError) as exc:
            add(f"source:{name}", False, str(exc))
            continue
        dockerfile = repo / 'Dockerfile'
        if dockerfile.is_file():
            for image in sorted(set(re.findall(r'^ARG \w+=(local/\S+)\s*$', dockerfile.read_text(errors='replace'), re.MULTILINE))):
                try:
                    image_id = capture(['docker','image','inspect','--format','{{.Id}}',image],15)
                    add('base-image:'+image, True, image_id)
                except (RuntimeError,OSError,subprocess.TimeoutExpired):
                    add('base-image:'+image, False, 'Build/import the matching CCE base image; do not retag an unrelated image')
        for asset in required_assets(repo):
            file = asset_path(repo, asset)
            valid = file.exists()
            if valid and file.is_file():
                with file.open("rb") as handle:
                    valid = b"git-lfs.github.com/spec" not in handle.read(160) and file.stat().st_size > 0
            add(f"asset:{name}/{asset}", valid, str(file))
    python_source = asset_path(ROOT / "public-service", "deps/Python-3.11.15.tgz")
    add("python-base-source", python_source.exists(), str(python_source))
    provider=cfg.get('AGENT_PROVIDER','codex')
    add('agent-provider',provider in {'codex','opencode'},provider)
    add("agent-cli", shutil.which(provider), "dedicated Linux Agent CLI required")
    if provider=='codex':
        auth = Path(cfg["CODEX_HOME"]) / "auth.json"
        add("codex-auth", auth.is_file(), "Complete login in the dedicated CODEX_HOME; no token is logged")
    elif provider=='opencode':
        add('opencode-config',Path(cfg.get('OPENCODE_CONFIG','')).is_file(), 'Dedicated provider configuration required')
        if cfg.get('OPENCODE_SMOKE_REPORT'):
            try:
                report_path=Path(cfg['OPENCODE_SMOKE_REPORT'])
                smoke=json.loads(report_path.read_text())
                fresh=report_path.stat().st_mtime >= Path(cfg['OPENCODE_CONFIG']).stat().st_mtime
                add('agent-tool-smoke',smoke.get('passed') is True and fresh,'Real tool smoke must pass for the current provider configuration')
            except (OSError,ValueError):
                add('agent-tool-smoke',False,'Run the real OpenCode tool smoke before E2E')
    add("multica-cli", shutil.which("multica"), "Dedicated Linux daemon binary required; do not use Windows daemon")
    harness = STATE / "playwright/node_modules/.bin/playwright"
    add("playwright", harness.is_file(), str(harness))
    for field in ("GM_MODEL", "GM_BASE_URL", "GM_API_KEY"):
        add(f"credential:{field}", bool(cfg.get(field)), f"Set {field} in {STATE / 'settings.json'}")
    if cfg.get("GM_BACKEND") == "codex-cli-chatgpt":
        try:
            with urlopen("http://127.0.0.1:18090/health", timeout=3) as response:
                adapter = json.load(response)
            add("codex-model-adapter", adapter.get("backend") == "codex-cli-chatgpt",
                "local subscribed CLI adapter; not CCE model-provider parity")
        except (OSError, ValueError):
            add("codex-model-adapter", False, "Start start-model.ps1; no API-key fallback")
    # Bootstrap credentials are checked here; runtime IDs are checked after registration.
    add("test-account", bool(cfg.get("TEST_ADMIN_PASSWORD")), "isolated test account")
    runtime_names = {'agent-cli', 'agent-provider', 'agent-tool-smoke', 'opencode-config', 'codex-auth', 'multica-cli', 'codex-model-adapter', 'test-account'}
    for check in checks:
        check['scope'] = 'runtime' if check['name'] in runtime_names or check['name'].startswith('credential:') else 'build'
        check['required'] = include_runtime or check['scope'] != 'runtime'
    return {"ok": all(c["ok"] for c in checks if c['required']), "checks": checks, "revisions": revisions,
            "model_backend": cfg.get("GM_BACKEND", "cce-api"),
            "cce_model_parity": cfg.get("GM_BACKEND") != "codex-cli-chatgpt",
            "settings_path": str(Path(os.environ.get('E2E_SETTINGS_FILE',STATE / 'settings.json'))),
            "platform": "Linux Compose / CCE images" if os.environ.get('PIPELINE_CLOUD_PROFILE')=='1' else "WSL Compose / CCE images"}


def snapshot(destination, revisions):
    """Archive committed sources only; never include ignored production configuration."""
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    lock = {"services": {}, "config_mode": "isolated-env", "harness_sha256": {}}
    for name in SOURCE_REPOS:
        repo = ROOT / name
        sha = revisions[name]
        target = destination / name
        target.mkdir(exist_ok=True)
        archive = destination / f"{name}.tar"
        subprocess.run(["git", "-c", f"safe.directory={repo}", "-C", str(repo),
                        "archive", "--format=tar", "-o", str(archive), sha], check=True)
        with tarfile.open(archive) as bundle:
            bundle.extractall(target, filter="data")
        archive.unlink()
        assets = {}
        for rel in required_assets(repo):
            source, dest = asset_path(repo, rel), target / rel
            if source.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
                with source.open("rb") as handle:
                    assets[rel] = hashlib.file_digest(handle, "sha256").hexdigest()
            elif source.is_dir() and not dest.exists():
                shutil.copytree(source, dest)
        lock["services"][name] = {"sha": sha, "assets": assets}
    for file in sorted(HERE.rglob("*")):
        if any(p in {"node_modules", ".state", "results", "__pycache__"} for p in file.relative_to(HERE).parts):
            continue
        if file.is_file() and file.suffix in {".py", ".yaml", ".sh", ".json", ".ts", ".cjs", ".ps1"}:
            lock["harness_sha256"][str(file.relative_to(HERE))] = hashlib.sha256(file.read_bytes()).hexdigest()
    output_json(destination / "sources.lock.json", lock)
    return lock


def runtime_environment(directory, images):
    cfg = config()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    previous = {}
    if (directory / "runtime.env").is_file():
        previous = dict(line.split("=", 1) for line in (directory / "runtime.env").read_text().splitlines() if "=" in line)
    db_password = previous.get("SQL_PASSWD") or secrets.token_urlsafe(24)
    env = {
        "SQL_SERVER": "postgres:5432", "SQL_PASSWD": db_password,
        "SQL_SSLMODE": "disable",
        "REDIS_SERVER": "redis:6379", "REDIS_PASSWD": "", "KAFKA_SERVER": "kafka:9092",
        "SERVICE_INTERNAL_TOKEN": previous.get("SERVICE_INTERNAL_TOKEN") or secrets.token_urlsafe(32),
        "JWT_SECRET": previous.get("JWT_SECRET") or secrets.token_urlsafe(32),
        "MULTICA_SERVER": "http://multica-server:8080", "AGENTLINK_SERVER": "http://agentlink:8643",
        "MATTERMOST_SERVER": "http://mattermost:8066", "GOVERNANCE_SERVER": "http://governance:8684",
        "GATEWAY_SERVER": "http://gateway:8081", "SCHEDULE_SERVER": "http://schedule:8766",
        "MEMORY_SERVER": "http://cellmem:8096", "TEMPORAL_SERVER": "temporal:7233",
        "TEMPORAL_HTTP_SERVER": "http://temporal:8233", "PLUGIN_MARKET_SERVER": "http://skills-market:8683",
        "IM_IDENTITY_SERVER": "http://mattermost:8066", "IM_CHAT_SERVER": "http://mattermost:8066",
        "CONFIG_SERVER": "", "SERVICE_ROUTER_HTTPS": "off", "MATTERMOST_TEST_DOMAIN": "localhost",
        "MATTERMOST_PUBLIC_URL": "http://localhost:18066", "MULTICA_PUBLIC_URL": "http://localhost:18080",
        "MM_ADMIN_USER": cfg["TEST_ADMIN_USER"], "MM_ADMIN_PASSWORD": cfg["TEST_ADMIN_PASSWORD"],
        "IM_IDENTITY_SERVER_USERNAME": cfg["TEST_ADMIN_USER"],
        "IM_IDENTITY_SERVER_PASSWORD": cfg["TEST_ADMIN_PASSWORD"],
        "IM_IDENTITY_SERVER_TENANT_ID": "pr-e2e-local",
        "IM_IDENTITY_SERVER_MAIN_DEPT_CODE": "pr-e2e",
        "IM_IDENTITY_SERVER_MAIN_CORP_DEPT_CODE": "pr-e2e",
        "SEMANTIC_GMAGENT_BASE_URL": "http://gmagent:3030",
        "SEMANTIC_IM_CONTEXT_CROSS_CHANNEL_MEMORY_ENABLED": "false",
    }
    if any("\n" in str(v) or "\r" in str(v) for v in env.values()):
        raise ValueError("Multiline environment values are not supported")
    env["MULTICA_IM_INTERNAL_TOKEN"] = env["SERVICE_INTERNAL_TOKEN"]
    env["GM_AGENT_ORCHESTRATION_TOKEN"] = env["SERVICE_INTERNAL_TOKEN"]
    env["SEMANTIC_GMAGENT_AUTH_TOKEN"] = env["SERVICE_INTERNAL_TOKEN"]
    file = directory / "runtime.env"
    file.write_text("\n".join(f"{k}={v}" for k, v in env.items()) + "\n")
    file.chmod(0o600)
    output_json(directory / "internal.json", {"token": env["SERVICE_INTERNAL_TOKEN"]}, private=True)
    # The IM adapter's outbound events must enter Router, not bypass it.
    mm_file = directory / "mattermost.env"
    mm_file.write_text("GATEWAY_SERVER=http://router:80\n")
    mm_file.chmod(0o600)
    compose_env = {**os.environ, **images, "E2E_ENV_FILE": str(file),
                   "E2E_MM_ENV_FILE": str(mm_file), "E2E_DB_PASSWORD": db_password,
                   "E2E_PRIVATE_DIR": str(directory), "E2E_STATE_DIR": str(STATE)}
    gm_file = directory / "gm.env"
    gm = {"GM_AGENT_PRIMARY_LLM_BASE_URL": cfg["GM_BASE_URL"],
          "GM_AGENT_PRIMARY_LLM_API_KEY": cfg["GM_API_KEY"],
          "GM_AGENT_PRIMARY_LLM_MODEL": cfg["GM_MODEL"]}
    if cfg.get("GM_BACKEND") == "codex-cli-chatgpt":
        gm.update(GM_AGENT_MODEL_ATTEMPT_TIMEOUT_SECONDS="180",
                  GM_AGENT_MODEL_TOTAL_TIMEOUT_SECONDS="240",
                  GM_AGENT_LLM_REQUEST_TIMEOUT_SECONDS="180",
                  GM_AGENT_LLM_ATTEMPT_TIMEOUT_SECONDS="180",
                  GM_AGENT_LLM_TOTAL_TIMEOUT_SECONDS="240")
    if any("\n" in v or "\r" in v for v in gm.values()):
        raise ValueError("Multiline model settings are not supported")
    # Compose format: raw preserves dollar signs in credentials.
    gm_file.write_text("\n".join(f"{k}={v}" for k, v in gm.items()) + "\n")
    gm_file.chmod(0o600)
    compose_env["E2E_GM_ENV_FILE"] = str(gm_file)
    return compose_env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["doctor"])
    args = parser.parse_args()
    result = doctor()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 2)


if __name__ == "__main__":
    main()
