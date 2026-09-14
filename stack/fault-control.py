#!/usr/bin/env python3
"""Control only the dedicated PR E2E daemon for resilience tests."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from stack import STATE, config


def owned(cfg):
    profile = str(cfg.get("LOCAL_DAEMON_PROFILE", ""))
    daemon_id = str(cfg.get("DAEMON_ID", ""))
    if not profile.startswith("pr-e2e-") or not daemon_id.startswith("pr-e2e-"):
        raise RuntimeError("refusing to control a non-E2E daemon")
    if cfg.get("E2E_RESILIENCE_ENABLED") is not True and os.environ.get("PIPELINE_FEATURE_RESILIENCE") != "true":
        raise RuntimeError("E2E resilience control is disabled")
    return profile, daemon_id


def base_env():
    return {**os.environ, "HOME": str(STATE / "daemon-home")}


def status(profile):
    cli = shutil.which("multica")
    if not cli:
        raise RuntimeError("multica CLI is unavailable")
    result = subprocess.run([cli, "daemon", "status", "--profile", profile, "--output", "json"],
                            env=base_env(), capture_output=True, text=True, timeout=15)
    if result.returncode:
        return {"status": "stopped", "detail": result.stderr[-500:]}
    try:
        return json.loads(result.stdout)
    except ValueError:
        return {"status": "unknown", "detail": result.stdout[-500:]}


def stop(profile):
    cli = shutil.which("multica")
    result = subprocess.run([cli, "daemon", "stop", "--profile", profile], env=base_env(),
                            capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError("dedicated daemon stop failed: " + result.stderr[-500:])
    return status(profile)


def crash(profile, daemon_id):
    health = status(profile)
    pid = int(health.get('pid') or 0)
    if health.get('status') != 'running' or pid <= 1:
        raise RuntimeError('dedicated daemon is not running')
    # pidfd prevents PID reuse from redirecting the signal to a different process.
    descriptor = os.pidfd_open(pid)
    try:
        proc = Path('/proc') / str(pid)
        if proc.stat().st_uid != os.getuid():
            raise RuntimeError('refusing to signal a daemon owned by another user')
        values = dict(item.split(b'=', 1) for item in (proc / 'environ').read_bytes().split(b'\0') if b'=' in item)
        if values.get(b'MULTICA_DAEMON_ID') != daemon_id.encode() or values.get(b'HOME') != str(STATE / 'daemon-home').encode():
            raise RuntimeError('daemon process identity does not match this run')
        if (proc / 'exe').resolve() != Path(shutil.which('multica')).resolve():
            raise RuntimeError('unexpected daemon executable')
        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
    finally:
        os.close(descriptor)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if status(profile).get('status') == 'stopped':
            return {'status': 'stopped', 'fault': 'process-crash', 'pid': pid}
        time.sleep(1)
    raise RuntimeError('dedicated daemon still reports running after crash')


def recover(private, cfg):
    from local_daemon import connect
    bootstrap = json.loads((private / "bootstrap.json").read_text())
    connect(private, {"id": cfg.get("CONTROL_USER_ID") or bootstrap["user_id"], "username": bootstrap["username"]})
    timeout = int(cfg.get("E2E_DAEMON_RECOVERY_SECONDS", 90))
    deadline = time.monotonic() + timeout
    profile = config()["LOCAL_DAEMON_PROFILE"]
    while time.monotonic() < deadline:
        health = status(profile)
        if health.get("status") == "running":
            # Reuse the browser identity already verified during bootstrap, not a new browser login.
            check = subprocess.run([sys.executable, str(Path(__file__).with_name("bootstrap.py")), "--check"],
                                   env={**os.environ, "E2E_DISCOVER_BROWSER_IDENTITY": "0"},
                                   capture_output=True, text=True, timeout=timeout)
            if check.returncode == 0:
                return {"status": "running", "readiness": "passed"}
        time.sleep(2)
    raise RuntimeError("dedicated daemon did not recover before the configured deadline")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("status", "stop", "crash", "recover"))
    args = parser.parse_args()
    cfg = config()
    profile, daemon_id = owned(cfg)
    private = Path(os.environ.get("E2E_PRIVATE_DIR", "")).resolve()
    expected = (STATE / "local-stack").resolve()
    if private != expected and os.environ.get("PIPELINE_CLOUD_PROFILE") != "1":
        raise RuntimeError("fault control requires the owned local-stack directory")
    if not (private / "internal.json").is_file() or not (private / "bootstrap.json").is_file():
        raise RuntimeError("private bootstrap evidence is unavailable")
    if args.action == "status":
        result = status(profile)
    elif args.action == "stop":
        result = stop(profile)
    elif args.action == "crash":
        result = crash(profile, daemon_id)
    else:
        result = recover(private, cfg)
    print(json.dumps({"action": args.action, "profile": profile, "daemon_id": daemon_id, **result}))


if __name__ == "__main__":
    main()
