"""Publish sanitized Pipeline evidence through the authenticated control channel."""
import argparse
import hashlib
import io
import json
import os
import subprocess
import ssl
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from pr_pipeline_hub import atomic_json, redact, utc_now
from evidence_redaction import known_secrets, sanitize


def inputs(root, completed):
    paths = list(root.glob("*.log"))
    artifacts = root / "artifacts"
    if completed:
        paths += list(artifacts.rglob("*"))
    else:
        paths += list(artifacts.glob("*/*/progress.ndjson"))
    return sorted(p for p in paths if p.is_file() and not p.is_symlink()
                  and p.resolve().is_relative_to(root.resolve())
                  and not {"private", ".env", "auth.json", "node_modules", ".git"}.intersection(p.relative_to(root).parts))


def publish(config, run_id):
    root = Path(config["data_dir"]) / "runs" / run_id
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(config["local_api_url"] + "/api/runs/" + run_id, timeout=20) as response:
        run = json.load(response)
    run["web_url"] = config["public_base_url"] + "/runs/" + run_id
    run["local_url"] = config["local_base_url"] + "/runs/" + run_id
    run["archive_synced_at"] = utc_now()
    run['publication']={'status':'published','at':run['archive_synced_at'],'web_url':run['web_url']}
    secrets=known_secrets(root)
    files = {"run.json": sanitize(json.dumps(run, ensure_ascii=False).encode(),secrets)}
    for path in inputs(root, run["status"] not in {"queued", "running"}):
        data = path.read_bytes()
        if path.suffix == ".log":
            data = redact(data.decode("utf-8", errors="replace")).encode()
        files[path.relative_to(root).as_posix()] = sanitize(data,secrets)
    manifest = {"run_id": run_id, "published_at": utc_now(), "execution_location": os.environ.get('PIPELINE_EXECUTION_LOCATION','Local WSL'),
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    files["manifest.json"] = json.dumps(manifest).encode()
    with tempfile.TemporaryFile() as archive:
        with tarfile.open(fileobj=archive, mode="w:gz") as tar:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o600
                tar.addfile(info, io.BytesIO(data))
        archive.seek(0)
        if config.get('control_url'):
            length=archive.seek(0,2);archive.seek(0)
            request=urllib.request.Request(config['control_url'].rstrip('/')+'/internal/artifacts',archive,
                {'Content-Type':'application/gzip','Content-Length':str(length),
                 'X-Worker-Token':os.environ['PIPELINE_WORKER_TOKEN']})
            with opener.open(request,timeout=900) as response:
                receipt=json.load(response)
            if receipt.get('run_id')!=run_id:raise RuntimeError('Archive receipt mismatch')
        else:
            publish_ssh(config,archive)
    atomic_json(root / "publication.json", {"status": "published", "at": utc_now(),
                "web_url": run["web_url"], "file_count": len(files), "manifest_sha256": hashlib.sha256(files["manifest.json"]).hexdigest()})
    print(run_id, "published", len(files), flush=True)


def publish_ssh(config, archive):
        command = [config["ssh_executable"], "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                   config["ssh_host"], "/usr/local/bin/python3.11 /opt/pr-e2e-share/share_viewer.py ingest"]
        sockets = sorted(Path('/run/WSL').glob('*_interop'), key=lambda p: p.stat().st_mtime)
        if sockets:
            os.environ['WSL_INTEROP'] = str(sockets[-1])
        result = subprocess.run(command, stdin=archive, capture_output=True, timeout=900)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace")[-1000:])


def fingerprint(root):
    run = json.loads((root / "run.json").read_text())
    paths = [root / "run.json"] + inputs(root, run["status"] not in {"queued", "running"})
    return hashlib.sha256(str([(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths]).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if args.run_id:
        publish(config, args.run_id)
        return
    cache_path = Path(config["data_dir"]) / "publication-cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    while True:
        try:
            context = ssl.create_default_context(cafile=str(args.config.parent / 'ecs-share.crt'))
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
            with opener.open(config['public_base_url'] + '/api/health', timeout=5) as response:
                health = json.load(response)
            if not health.get('read_only'):
                raise RuntimeError('Public URL does not point to the ECS archive')
            public_health = {'reachable': True, 'checked_at': utc_now()}
        except Exception as exc:
            public_health = {'reachable': False, 'checked_at': utc_now(), 'error': redact(str(exc))}
        atomic_json(Path(config['data_dir']) / 'share-health.json', public_health)
        for root in sorted((Path(config["data_dir"]) / "runs").glob("*")):
            if root.name < config["first_run"] or not (root / "run.json").is_file():
                continue
            try:
                stamp = fingerprint(root) + config['public_base_url']
                if cache.get(root.name) == stamp:
                    continue
                publish(config, root.name)
                cache[root.name] = stamp
                atomic_json(cache_path, cache)
            except Exception as exc:
                atomic_json(root / "publication.json", {"status": "error", "at": utc_now(), "error": redact(str(exc))})
                print(root.name, type(exc).__name__, redact(str(exc)), flush=True)
        time.sleep(config.get("poll_seconds", 10))


if __name__ == "__main__":
    main()
