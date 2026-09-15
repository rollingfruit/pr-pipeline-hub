#!/usr/bin/env python3
"""Bootstrap only the isolated Mattermost test tenant and selected real runtime."""
import argparse
import json
import os
import subprocess
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from stack import config, output_json
from local_daemon import connect

BASE = os.environ.get("E2E_APP_URL", "http://localhost:18066")
MULTICA = os.environ.get('E2E_MULTICA_URL', 'http://127.0.0.1:18080').rstrip('/')


def request(path, method="GET", data=None, token=""):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(BASE + path, data=None if data is None else json.dumps(data).encode(),
                  headers=headers, method=method)
    with urlopen(req, timeout=15) as response:
        raw = response.read()
        return (json.loads(raw) if raw else {}), response.headers


def ready_runtime_ids(cfg, user, provider):
    """Older app projections omit metadata; validate the same ID at the source."""
    from local_daemon import provider_ready
    private = Path(os.environ['E2E_PRIVATE_DIR'])
    internal = json.loads((private / 'internal.json').read_text())['token']
    query = urlencode({'workspace_id': cfg['WORKSPACE_ID'], 'team_id': 'hw', 'user_id': user['id']})
    req = Request(MULTICA + '/v1/agent/im-integrations/runtimes?' + query,
                  headers={'X-Auth-Token': internal})
    with urlopen(req, timeout=15) as response:
        payload = json.load(response)
    rows = payload if isinstance(payload, list) else payload.get('runtimes', [])
    return {r['id'] for r in rows if r.get('daemon_id') == cfg['DAEMON_ID']
            and r.get('workspace_id') == cfg['WORKSPACE_ID'] and r.get('provider') == provider
            and r.get('status') == 'online' and r.get('publishable_for_current_user') is True
            and provider_ready(r, provider)}


def bootstrap(check=False, connect_only=False):
    cfg = config()
    provider = cfg.get('AGENT_PROVIDER','codex')
    if provider not in {'codex','opencode'}:
        raise RuntimeError('Unsupported test Agent provider')
    if not os.environ.get("E2E_PRIVATE_DIR"):
        raise RuntimeError("Use the Pipeline-generated isolated environment")
    request("/api/v4/system/ping")
    try:
        user, headers = request("/api/v4/users/login", "POST", {
            "login_id": cfg["TEST_ADMIN_USER"], "password": cfg["TEST_ADMIN_PASSWORD"]})
    except HTTPError as exc:
        if check or exc.code not in {400, 401, 404}:
            raise
        # Account creation is fixture preparation, never the E01 bot action.
        request("/api/v4/users", "POST", {"username": cfg["TEST_ADMIN_USER"],
                "password": cfg["TEST_ADMIN_PASSWORD"], "email": cfg.get('TEST_ADMIN_EMAIL', "pr-e2e-admin@example.invalid")})
        user, headers = request("/api/v4/users/login", "POST", {
            "login_id": cfg["TEST_ADMIN_USER"], "password": cfg["TEST_ADMIN_PASSWORD"]})
    if os.environ.get('E2E_DISCOVER_BROWSER_IDENTITY') == '1':
        probe = Path(__file__).resolve().parent / 'playwright/identity-probe.cjs'
        subprocess.run(['node', str(probe)], check=True, timeout=120)
        identity_file = Path(os.environ['E2E_PRIVATE_DIR']) / 'browser-identity.json'
        browser_identity = json.loads(identity_file.read_text())
        if browser_identity['user_id'] != user['id'] or browser_identity['username'] != user['username']:
            raise RuntimeError('Browser identity does not match fixture account')
        cfg['CONTROL_USER_ID'] = browser_identity['control_user_id']
        output_json(Path(os.environ['E2E_SETTINGS_FILE']), cfg, private=True)
    control_user = {**user, 'id': cfg.get('CONTROL_USER_ID') or user['id']}
    token = headers.get("Token")
    if not token:
        raise RuntimeError("Mattermost did not issue a test session")
    try:
        team, _ = request("/api/v4/teams/name/hw", token=token)
    except HTTPError as exc:
        if check or exc.code != 404:
            raise
        team, _ = request("/api/v4/teams", "POST", {"name": "hw", "display_name": "PR E2E", "type": "O"}, token)
        request(f"/api/v4/teams/{team['id']}/members", "POST",
                {"team_id": team["id"], "user_id": user["id"]}, token)
    identity = urlencode({"user_id": control_user["id"], "user_name": user["username"]})
    if not check:
        cfg = connect(os.environ["E2E_PRIVATE_DIR"], control_user)
    if connect_only:
        private = Path(os.environ["E2E_PRIVATE_DIR"])
        internal = json.loads((private / "internal.json").read_text())["token"]
        query = urlencode({"workspace_id": cfg["WORKSPACE_ID"], "team_id": "hw", "user_id": control_user["id"]})
        for _ in range(60):
            req = Request(MULTICA + "/v1/agent/im-integrations/runtimes?" + query,
                          headers={"X-Auth-Token": internal})
            with urlopen(req, timeout=10) as response:
                data = json.load(response)
            rows = data if isinstance(data, list) else data.get("runtimes", [])
            from local_daemon import provider_ready
            runtime = next((r for r in rows if r.get("daemon_id") == cfg["DAEMON_ID"]
                            and provider_ready(r, provider)
                            and r.get("status") == "online" and r.get("provider") == provider
                            and r.get("publishable_for_current_user") is True), None)
            if runtime:
                from stack import STATE
                cfg["RUNTIME_ID"] = runtime["id"]
                output_json(Path(os.environ.get('E2E_SETTINGS_FILE', STATE / 'settings.json')), cfg, private=True)
                output_json(private / "control-plane.json", {"user_id": user["id"], "username": user["username"],
                            "team_id": team["id"], "runtime": runtime, "business_e2e_passed": False}, private=True)
                print(json.dumps({"control_plane_ready": True, "user_id": user["id"], "runtime_id": runtime["id"],
                                  "provider": provider, "status": "online", "business_e2e_passed": False}))
                return
            time.sleep(2)
        raise RuntimeError("Daemon did not publish the selected runtime to the local control plane")
    for _ in range(60):
        from local_daemon import provider_ready
        managed, _ = request("/v1/agent/managed-platforms?" + identity, token=token)
        ready_ids = ready_runtime_ids(cfg, control_user, provider)
        runtime = next((r for r in managed.get("runtimes", [])
                        if r.get("daemon_id") == cfg.get("DAEMON_ID")
                        and r.get('id') in ready_ids
                        and r.get("publishable_for_current_user") is True and r.get("status") == "online"
                        and (r.get("provider") or r.get("runtime_provider")) == provider), None)
        if runtime:
            cfg["RUNTIME_ID"] = runtime["id"]
            from stack import STATE
            output_json(Path(os.environ.get('E2E_SETTINGS_FILE', STATE / 'settings.json')), cfg, private=True)
            break
        time.sleep(2)
    managed, _ = request("/v1/agent/managed-platforms?" + identity, token=token)
    ready_ids = ready_runtime_ids(cfg, control_user, provider)
    runtimes = [r for r in managed.get("runtimes", [])
                if r.get("publishable_for_current_user") is True and r.get("status") == "online"
                and r.get('id') in ready_ids
                and (r.get("provider") or r.get("runtime_provider")) == provider
                and r.get("location", "local") == "local"]
    # Do not silently bind a developer's daemon or a cloud runtime.
    runtime = next((r for r in runtimes if r.get("id") == cfg.get("RUNTIME_ID")
                    and r.get("daemon_id") == cfg.get("DAEMON_ID")), None)
    if runtime is None:
        raise RuntimeError("Dedicated Agent daemon is not owned, online and publishable; see private daemon logs")
    if not Path(cfg["TEST_WORKSPACE"]).is_dir():
        raise RuntimeError("Dedicated TEST_WORKSPACE does not exist")
    evidence = {"user_id": user["id"], "username": user["username"], "team_id": team["id"],
                "runtime": runtime, "checked_at": time.time()}
    output_json(Path(os.environ["E2E_PRIVATE_DIR"]) / "bootstrap.json", evidence, private=True)
    print(json.dumps({"ready": True, "user_id": user["id"], "runtime_id": runtime["id"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--connect-only", action="store_true")
    args = parser.parse_args()
    bootstrap(args.check, args.connect_only)
