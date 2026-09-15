"""Register an isolated Linux daemon through the production Multica contract."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid
from urllib.request import Request, urlopen

from stack import STATE, config, output_json


def provider_ready(runtime, provider):
    if provider != 'opencode':
        return True
    metadata = runtime.get('metadata') or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            return False
    return (isinstance(metadata, dict) and bool(metadata.get('version'))
            and metadata.get('provider_ready') is True)


def configure_opencode_auth(home, config_file):
    home = Path(home)
    key = (Path(config_file).resolve().parent / 'modelarts-key').read_text().strip()
    if not key or any(char.isspace() for char in key):
        raise RuntimeError('Dedicated ModelArts credential is missing or invalid')
    data_home = home / '.local' / 'share'
    auth_dir = data_home / 'opencode'
    auth_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    auth_dir.chmod(0o700)
    output_json(auth_dir / 'auth.json', {'modelarts': {'type': 'api', 'key': key}}, private=True)
    return {'XDG_DATA_HOME': str(data_home), 'XDG_CONFIG_HOME': str(home / '.config'),
            'XDG_CACHE_HOME': str(home / '.cache')}


def configure_fixture_access(home, config_file, fixture_path):
    fixture = Path(fixture_path).resolve(strict=True)
    if not fixture.is_dir() or fixture == STATE.parent.resolve() or not fixture.is_relative_to(STATE.parent.resolve()):
        raise RuntimeError('Fixture access must stay inside this isolated execution directory')
    provider_config = json.loads(Path(config_file).read_text())
    provider_config.setdefault('permission', {})['external_directory'] = {
        '*': 'deny', str(fixture): 'allow', str(fixture) + '/**': 'allow'}
    isolated_config = Path(home) / 'opencode-fixture.json'
    output_json(isolated_config, provider_config, private=True)
    return str(isolated_config)


def connect(private, user):
    private = Path(private)
    cfg = config()
    home = STATE / "daemon-home"
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile = cfg.get("LOCAL_DAEMON_PROFILE") or ("pr-e2e-" + uuid.uuid4().hex[:8])
    if not profile.startswith("pr-e2e-"):
        raise RuntimeError("Refusing a non-test daemon profile")
    daemon_id = cfg.get("DAEMON_ID") or ("pr-e2e-wsl-" + uuid.uuid4().hex)
    if not daemon_id.startswith("pr-e2e-wsl-"):
        raise RuntimeError("Refusing to rebind an existing developer daemon")
    token = json.loads((private / "internal.json").read_text())["token"]
    server_url = os.environ.get('E2E_MULTICA_URL', 'http://127.0.0.1:18080').rstrip('/')
    request = Request(server_url + "/v1/agent/im-integrations/actions/connect-daemon",
                      data=json.dumps({"team_id": "hw", "user_id": user["id"], "daemon_id": daemon_id}).encode(),
                      headers={"Content-Type": "application/json", "X-Auth-Token": token})
    with urlopen(request, timeout=30) as response:
        binding = json.load(response)
    if binding.get("daemon_id") != daemon_id or not binding.get("workspace_id") or not binding.get("daemon_token"):
        raise RuntimeError("Incomplete local daemon binding")
    cli = shutil.which("multica")
    provider = cfg.get('AGENT_PROVIDER', 'codex')
    if provider not in {'codex','opencode'}:
        raise RuntimeError('Unsupported test Agent provider')
    agent = shutil.which(provider)
    if not cli or not agent:
        raise RuntimeError("Linux Multica and selected Agent executables required")
    env = {**os.environ, "HOME": str(home),
           "MULTICA_SERVER_URL": server_url, "MULTICA_TOKEN": binding["daemon_token"],
           "MULTICA_WORKSPACE_ID": binding["workspace_id"], "MULTICA_DAEMON_ID": daemon_id,
           "MULTICA_IM_USER_ID": user["id"], "MULTICA_IM_USERNAME": user["username"],
           "MULTICA_WORKSPACES_ROOT": str(STATE / "daemon-workspaces"), "MULTICA_DAEMON_AUTO_UPDATE": "false",
           "MULTICA_DAEMON_MAX_CONCURRENT_TASKS": "1", "MULTICA_LLM_IO_LOG": "false",
           "HTTPS_PROXY": cfg.get("CODEX_PROXY", ""), "HTTP_PROXY": cfg.get("CODEX_PROXY", ""),
           "NO_PROXY": "localhost,127.0.0.1,::1"}
    if provider == 'codex':
        env.update(CODEX_HOME=cfg['CODEX_HOME'],MULTICA_CODEX_PATH=agent,MULTICA_CODEX_MODEL=cfg['CODEX_MODEL'])
    else:
        # Multica probes `opencode auth list`; file-only provider options are
        # usable for inference but are not counted by that readiness contract.
        env.update(configure_opencode_auth(home, cfg['OPENCODE_CONFIG']))
        if cfg.get('E2E_SINGLE_PROVIDER') is True:
            # An explicit missing override disables discovery without changing host tools.
            disabled = home / 'disabled-providers' / 'codex'
            if disabled.exists():
                raise RuntimeError('Unexpected executable at disabled provider path')
            env['MULTICA_CODEX_PATH'] = str(disabled)
        env.update(MULTICA_OPENCODE_PATH=agent, MULTICA_OPENCODE_MODEL=cfg['OPENCODE_MODEL'],
                   OPENCODE_CONFIG=cfg['OPENCODE_CONFIG'], OPENCODE_DISABLE_AUTOUPDATE='true',
                   OPENCODE_DISABLE_MODELS_FETCH='true',OPENCODE_DISABLE_DEFAULT_PLUGINS='true')
        if cfg.get('OPENCODE_FIXTURE_ACCESS') is True:
            env['OPENCODE_CONFIG'] = configure_fixture_access(home, cfg['OPENCODE_CONFIG'], cfg['TEST_WORKSPACE'])
        probe = subprocess.run([agent, 'auth', 'list'], env=env, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=30)
        if probe.returncode or 'modelarts' not in probe.stdout.lower():
            raise RuntimeError('OpenCode cannot read the dedicated ModelArts authentication')
    for name in ('GH_TOKEN','GITHUB_TOKEN','PIPELINE_WORKER_TOKEN','PIPELINE_DATABASE_URL','PIPELINE_SUBMIT_PASSWORD'):
        env.pop(name,None)
    if cfg.get("LOCAL_DAEMON_PROFILE"):
        status = subprocess.run([cli, "daemon", "status", "--profile", profile, "--output", "json"],
                                env=env, capture_output=True, text=True, timeout=10, check=True)
        health = json.loads(status.stdout)
        if health.get("status") in ("running", "starting") and health.get("daemon_id") != daemon_id:
            raise RuntimeError("Daemon health-port collision; refusing to stop another daemon")
        subprocess.run([cli, "daemon", "stop", "--profile", profile], env=env, capture_output=True, timeout=30)
    result = subprocess.run([cli, "daemon", "start", "--profile", profile, "--no-auto-update"],
                            env=env, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError("Dedicated daemon start failed; inspect private daemon-home logs")
    cfg.update(DAEMON_ID=daemon_id, WORKSPACE_ID=binding["workspace_id"], LOCAL_DAEMON_PROFILE=profile, RUNTIME_ID="")
    output_json(Path(os.environ.get("E2E_SETTINGS_FILE", STATE / "settings.json")), cfg, private=True)
    output_json(private / "daemon-binding.json", {"daemon_id": daemon_id, "workspace_id": binding["workspace_id"],
                "profile": profile, "user_id": user["id"], "source": "local CCE Multica image", "backend": provider}, private=True)
    return cfg
