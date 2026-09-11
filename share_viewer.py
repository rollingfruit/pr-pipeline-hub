"""Read-only ECS archive viewer. Receives trusted local results over SSH only."""
import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import tarfile
import tempfile
import threading
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pr_pipeline_hub import PipelineHub, PipelineRequestHandler, atomic_json, utc_now


def ingest(root, stream):
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix="incoming-") as temp:
        dest = Path(temp)
        total = 0
        members = set()
        with tarfile.open(fileobj=stream, mode="r|gz") as archive:
            for member in archive:
                path = dest / member.name
                normalized = path.resolve()
                if normalized in members or not member.isfile() or not normalized.is_relative_to(dest) or member.size > 1024**3:
                    raise ValueError("Unsafe archive member")
                members.add(normalized)
                total += member.size
                if total > 4 * 1024**3:
                    raise ValueError("Archive too large")
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, path.open("wb") as target:
                    shutil.copyfileobj(source, target)
                path.chmod(0o640)
                shutil.chown(path, group="prpipeline")
        manifest = json.loads((dest / "manifest.json").read_text())
        run_id = manifest["run_id"]
        if not re.fullmatch(r"[A-Za-z0-9-]+", run_id):
            raise ValueError("Invalid run ID")
        expected = {(dest / name).resolve() for name in manifest['files']} | {(dest/'manifest.json').resolve()}
        if members != expected or 'run.json' not in manifest['files']:
            raise ValueError('Manifest must cover every artifact')
        if json.loads((dest/'run.json').read_text()).get('id') != run_id:
            raise ValueError('Run identity mismatch')
        for name, digest in manifest["files"].items():
            path = dest / name
            if not path.resolve().is_relative_to(dest) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("Artifact checksum mismatch")
        versions = root / "snapshots" / run_id
        versions.mkdir(parents=True, exist_ok=True)
        version = versions / secrets.token_hex(8)
        dest.chmod(0o750)
        shutil.chown(dest, group="prpipeline")
        shutil.move(str(dest), version)
        runs = root / "runs"
        runs.mkdir(exist_ok=True)
        link = runs / (run_id + '.' + secrets.token_hex(8) + ".next")
        link.symlink_to(version, target_is_directory=True)
        link.replace(runs / run_id)
        # Keep the prior snapshot briefly so in-flight browser requests remain valid.
        import time
        for old in versions.iterdir():
            if old != version and time.time() - old.stat().st_mtime > 3600:
                shutil.rmtree(old)
    receipt={"run_id": run_id, "published_at": utc_now(), "files": len(manifest["files"])}
    print(json.dumps(receipt))
    return receipt


class ArchiveHub:
    def __init__(self, root):
        self.runs_dir = root / "runs"
        self.public_base_url = os.environ["PIPELINE_PUBLIC_BASE_URL"]
        self.allowed_repos = set()
        self.lock = threading.RLock()

    def list_runs(self):
        values = [self.get_run(p.name) for p in sorted(self.runs_dir.glob("*"), reverse=True) if p.is_dir()]
        return [value for value in values if value][:100]

    def get_run(self, run_id):
        try:
            value = json.loads((self.runs_dir / run_id / "run.json").read_text())
            artifacts = self.runs_dir / run_id / 'artifacts'
            value['trace_downloads'] = [
                {'phase': p.relative_to(artifacts).parts[0], 'suite': p.relative_to(artifacts).parts[1],
                 'url': '/artifacts/' + run_id + '/' + p.relative_to(artifacts).as_posix()}
                for p in sorted(artifacts.glob('*/*/test-results/**/trace.zip'))]
            manifest_path = self.runs_dir / run_id / 'manifest.json'
            manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
            value["archive"] = {"read_only": True, "synced_at": value.get("archive_synced_at"),
                                "execution_location": manifest.get('execution_location', 'Local WSL')}
            return value
        # A partially published or incorrectly permissioned diagnostic must not
        # make the complete dashboard unavailable.
        except (OSError, json.JSONDecodeError, UnicodeError):
            return None

    def read_log(self, run_id, stage_id):
        path = self.runs_dir / run_id / (stage_id + ".log")
        return path.read_text(errors="replace")[-256000:] if path.is_file() else "No log uploaded yet."


class ArchiveHandler(PipelineRequestHandler):
    def log_message(self, fmt, *args):
        # Never put bearer URLs into access logs.
        print(self.command, urlparse(self.path).path, flush=True)

    def _view_authorized(self, query):
        token = os.environ["PIPELINE_VIEW_TOKEN"]
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except Exception:
            return False
        supplied = self.headers.get("X-Pipeline-View-Token", "") or parse_qs(query).get("access_token", [""])[0]
        cookie_name = 'pipeline_view' if self.headers.get('X-Forwarded-Proto') == 'https' else 'pipeline_view_http'
        if not supplied and cookie_name in cookies:
            supplied = cookies[cookie_name].value
        return secrets.compare_digest(token, supplied)

    def end_headers(self):
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        token = parse_qs(parsed.query).get("access_token", [""])[0]
        if token and self._view_authorized(parsed.query):
            self.send_response(303)
            secure = self.headers.get('X-Forwarded-Proto') == 'https'
            cookie_name = 'pipeline_view' if secure else 'pipeline_view_http'
            self.send_header("Set-Cookie", cookie_name + "=" + token + "; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800" + ('; Secure' if secure else ''))
            self.send_header("Location", parsed.path)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if parsed.path == "/api/health":
            self._json({"status": "ok", "runner": "Local WSL / ECS archive", "read_only": True,
                        "public_base_url": self.hub.public_base_url, "shareable_links": True})
            return
        if not self._view_authorized(parsed.query):
            self._error(401, "Open the authorized sharing link provided by the robot.")
            return
        return super().do_GET()

    def do_POST(self):
        self._error(405, "Read-only archive. Submit builds to the local Pipeline Hub.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["serve", "ingest"])
    parser.add_argument("--root", type=Path, default=Path("/var/lib/pr-e2e-share"))
    args = parser.parse_args()
    if args.mode == "ingest":
        ingest(args.root, sys.stdin.buffer)
        return
    if not os.environ.get("PIPELINE_VIEW_TOKEN"):
        raise RuntimeError("PIPELINE_VIEW_TOKEN is mandatory")
    server = ThreadingHTTPServer(("127.0.0.1", 8791), ArchiveHandler)
    server.hub = ArchiveHub(args.root)
    server.serve_forever()


if __name__ == "__main__":
    main()
