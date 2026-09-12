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
            anchor = db.execute('SELECT jump_host,nodes_json FROM environments WHERE id=?', ('a5932430eb2f',)).fetchone()
            self._gamma_anchor = dict(anchor) if anchor else None
        self.environment['nodes'] = json.loads(self.environment['nodes_json'])
        self.creds = cce_rollout.overlay_environment_passwords(
            cce_rollout.resolve_credentials(cfg, helper_root=root), self.environment)
        self.servers = []
        self.jump = self.node = None
        self._connection_lock = threading.RLock()

    def assert_dev_gamma(self):
        anchor = self._gamma_anchor
        if (not anchor or self.namespace != 'default'
                or self.environment['jump_host'] != anchor['jump_host']
                or sorted(self.environment['nodes']) != sorted(json.loads(anchor['nodes_json']))):
            raise PermissionError('Administrative operation is restricted to the configured dev-gamma cluster')

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

    @staticmethod
    def _active(client):
        if client is None:
            return False
        transport = client.get_transport()
        return bool(transport and transport.is_active() and transport.is_authenticated())

    def _close_clients(self):
        for client in (self.node, self.jump):
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
        self.node = self.jump = None

    def _connect_unlocked(self):
        self._close_clients()
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
        self._close_clients()
        raise RuntimeError('No cluster node available: ' + ', '.join(errors))

    def connect(self):
        with self._connection_lock:
            if self._active(self.jump) and self._active(self.node):
                return self
            return self._connect_unlocked()

    def _open_channel(self, destination, port, source):
        last_error = None
        for attempt in range(2):
            with self._connection_lock:
                if not (self._active(self.jump) and self._active(self.node)):
                    self._connect_unlocked()
                try:
                    return self.node.get_transport().open_channel(
                        'direct-tcpip', (destination, port), source, timeout=15)
                except Exception as error:
                    last_error = error
                    self._close_clients()
            if attempt == 0:
                continue
        raise RuntimeError('Gamma SSH tunnel unavailable after reconnect') from last_error

    def forward(self, destination, port, local_port):
        owner = self
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                channel = None
                try:
                    channel = owner._open_channel(destination, port, self.request.getpeername())
                    while True:
                        ready, _, _ = select.select([self.request, channel], [], [], 30)
                        for source in ready:
                            data = source.recv(65536)
                            if not data:
                                return
                            (channel if source is self.request else self.request).sendall(data)
                except Exception:
                    return
                finally:
                    if channel is not None:
                        try:
                            channel.close()
                        except Exception:
                            pass
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
        with self._connection_lock:
            self._close_clients()
