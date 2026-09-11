"""Run the local Hub, publishing worker, and loopback port-80 alias."""
import argparse
import http.client
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class LocalAlias(BaseHTTPRequestHandler):
    def proxy(self):
        length = int(self.headers.get('Content-Length', 0))
        if length > 64000:
            self.send_error(413)
            return
        connection = http.client.HTTPConnection('127.0.0.1', 8788, timeout=30)
        try:
            headers = {k: v for k, v in self.headers.items() if k.lower() not in {'host', 'connection'}}
            headers['Host'] = '127.0.0.1'
            connection.request(self.command, self.path, self.rfile.read(length) if length else None, headers)
            response = connection.getresponse()
            self.send_response(response.status)
            for name, value in response.getheaders():
                if name.lower() not in {'connection', 'transfer-encoding', 'server', 'date'}:
                    self.send_header(name, value)
            self.end_headers()
            while data := response.read(65536):
                self.wfile.write(data)
        except OSError:
            self.close_connection = True
        finally:
            connection.close()

    do_GET = proxy
    do_POST = proxy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['hub', 'publisher', 'alias', 'install'])
    args = parser.parse_args()
    if args.mode == 'install':
        for name, mode in [('pr-e2e-local-hub', 'hub'), ('pr-e2e-publisher', 'publisher'), ('pr-e2e-local-url', 'alias')]:
            Path('/etc/systemd/system/' + name + '.service').write_text(f'''[Unit]
Description=Local PR E2E {mode}
After=network.target
[Service]
Type=simple
WorkingDirectory={ROOT}
ExecStart=/usr/bin/python3 {ROOT}/local_services.py {mode}
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
''')
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        return
    if args.mode == 'alias':
        ThreadingHTTPServer(('127.0.0.1', 80), LocalAlias).serve_forever()
        return
    sockets = sorted(Path('/run/WSL').glob('*_interop'), key=lambda p: p.stat().st_mtime)
    if sockets:
        os.environ['WSL_INTEROP'] = str(sockets[-1])
    config = json.loads((ROOT / '.runtime/pipeline-server.json').read_text())
    if args.mode == 'publisher':
        os.execv('/usr/bin/python3', ['python3', str(ROOT / 'publish_results.py'), '--config', str(ROOT / '.runtime/pipeline-server.json')])
    local = json.loads((ROOT / '.runtime/pipeline-local.json').read_text())
    os.environ.update(PIPELINE_PUBLIC_BASE_URL=config['public_base_url'], PIPELINE_SHARE_TOKEN=config['view_token'],
                      PIPELINE_LOCAL_BASE_URL=local['base_url'], PIPELINE_EMBED_VIEW_TOKEN='false',
                      PIPELINE_ALLOWED_REPOS=local['allowed_repos'])
    if (ROOT / '.runtime/ecs-worker.enabled').exists():
        os.environ['PIPELINE_CONTROL_MODE'] = 'ecs'
        agent = json.loads((ROOT / '.runtime/pipeline-agent.json').read_text())
        if not agent.get('trigger_token'):
            raise RuntimeError('Authenticated local trigger token required')
        os.environ['PIPELINE_TRIGGER_TOKEN'] = agent['trigger_token']
    os.execv('/usr/bin/python3', ['python3', str(ROOT / 'pr_pipeline_hub.py'), '--host', '127.0.0.1', '--port', '8788',
                                '--data-dir', config['data_dir']])


if __name__ == '__main__':
    main()
