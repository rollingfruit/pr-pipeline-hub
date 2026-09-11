"""CI-only access using the existing Robot CI environment connection contract."""
import json
import os
from pathlib import Path
import select
import shlex
import socketserver
import sqlite3
import sys
import threading


class GammaAccess:
    def __init__(self, environment_id, robot_root='/opt/swr-push-helper'):
        root = Path(robot_root)
        sys.path.insert(0, str(root))
        import cce_rollout
        self.adapter = cce_rollout
        cfg = json.loads((root / 'config.json').read_text())
        self.namespace = str(cfg.get('cce_namespace') or 'default')
        with sqlite3.connect(f'file:{root}/data/robot-ci.db?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM environments WHERE id=?', (environment_id,)).fetchone()
            if row is None:
                raise ValueError('Unknown Robot CI environment ID')
            self.environment = dict(row)
        self.environment['nodes'] = json.loads(self.environment['nodes_json'])
        self.creds = cce_rollout.overlay_environment_passwords(
            cce_rollout.resolve_credentials(cfg, helper_root=root), self.environment)
        self.servers = []
        self.jump = self.node = None

    def remote(self, command, timeout=60):
        code, out, err = self.adapter.exec_via_nodes(command,
            jump_host=self.environment['jump_host'], nodes=self.environment['nodes'],
            creds=self.creds, timeout=timeout)
        if code:
            raise RuntimeError('Cluster command failed (exit %s)' % code)
        return out

    def resource(self, kind, name=''):
        return json.loads(self.remote('kubectl -n %s get %s %s -o json' % (
            shlex.quote(self.namespace), shlex.quote(kind), shlex.quote(name) if name else '')))

    def connect(self):
        paramiko = self.adapter._import_paramiko()
        jump_user, host, port = self.adapter.parse_ssh_target(self.environment['jump_host'])
        self.jump = paramiko.SSHClient()
        self.jump.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        options = dict(username=jump_user, port=port, timeout=20, banner_timeout=20,
                       auth_timeout=20, password=self.creds.get('jump_password') or None)
        if self.creds.get('ssh_key'):
            options['key_filename'] = os.path.expanduser(self.creds['ssh_key'])
        self.jump.connect(host, **options)
        self.jump.get_transport().set_keepalive(15)
        errors = []
        for address in self.environment['nodes']:
            user, node, port = self.adapter.parse_ssh_target(address, default_user=self.creds.get('node_user') or 'root')
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                channel = self.jump.get_transport().open_channel('direct-tcpip', (node, port), ('127.0.0.1', 0))
                client.connect(node, port=port, username=user, sock=channel,
                    password=self.creds.get('node_password') or None,
                    key_filename=options.get('key_filename'), timeout=20, auth_timeout=20)
                self.node = client
                client.get_transport().set_keepalive(15)
                return self
            except Exception as error:
                errors.append(type(error).__name__)
                client.close()
        self.close()
        raise RuntimeError('No cluster node available: ' + ', '.join(errors))

    def forward(self, destination, port, local_port):
        transport = self.node.get_transport()
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                channel = None
                try:
                    channel = transport.open_channel('direct-tcpip', (destination, port), self.request.getpeername(), timeout=15)
                    while True:
                        ready, _, _ = select.select([self.request, channel], [], [], 30)
                        for source in ready:
                            data = source.recv(65536)
                            if not data:
                                return
                            (channel if source is self.request else self.request).sendall(data)
                except (OSError, EOFError):
                    return
                finally:
                    if channel is not None:
                        channel.close()
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True
        server = Server(('127.0.0.1', local_port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.servers.append(server)
        return 'http://127.0.0.1:' + str(server.server_address[1])

    def close(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()
        for client in (self.node, self.jump):
            if client is not None:
                client.close()
