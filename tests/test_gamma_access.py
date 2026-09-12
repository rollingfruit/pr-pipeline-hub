import threading
import unittest

from gamma_access import GammaAccess


class FakeTransport:
    def __init__(self, active=True, authenticated=True, error=None):
        self.active = active
        self.authenticated = authenticated
        self.error = error
        self.calls = 0

    def is_active(self):
        return self.active

    def is_authenticated(self):
        return self.authenticated

    def open_channel(self, *args, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return 'channel'


class FakeClient:
    def __init__(self, transport):
        self.transport = transport
        self.closed = False

    def get_transport(self):
        return self.transport

    def close(self):
        self.closed = True


def access_with(jump, node):
    access = GammaAccess.__new__(GammaAccess)
    access.jump = jump
    access.node = node
    access.servers = []
    access._connection_lock = threading.RLock()
    return access


class GammaAccessTests(unittest.TestCase):
    def test_reuses_healthy_nested_connection(self):
        jump_transport = FakeTransport()
        node_transport = FakeTransport()
        access = access_with(FakeClient(jump_transport), FakeClient(node_transport))

        self.assertEqual('channel', access._open_channel('10.0.0.1', 80, ('127.0.0.1', 1)))
        self.assertEqual(1, node_transport.calls)

    def test_reconnects_when_nested_transport_is_inactive(self):
        old_jump = FakeClient(FakeTransport(active=False))
        old_node = FakeClient(FakeTransport(active=False))
        access = access_with(old_jump, old_node)
        new_jump = FakeClient(FakeTransport())
        new_node = FakeClient(FakeTransport())

        def reconnect():
            access._close_clients()
            access.jump = new_jump
            access.node = new_node
            return access

        access._connect_unlocked = reconnect
        self.assertEqual('channel', access._open_channel('10.0.0.1', 80, ('127.0.0.1', 2)))
        self.assertTrue(old_jump.closed)
        self.assertTrue(old_node.closed)
        self.assertEqual(1, new_node.transport.calls)

    def test_retries_channel_once_with_a_new_connection(self):
        old_jump = FakeClient(FakeTransport())
        old_node = FakeClient(FakeTransport(error=RuntimeError('session inactive')))
        access = access_with(old_jump, old_node)
        new_jump = FakeClient(FakeTransport())
        new_node = FakeClient(FakeTransport())

        def reconnect():
            access._close_clients()
            access.jump = new_jump
            access.node = new_node
            return access

        access._connect_unlocked = reconnect
        self.assertEqual('channel', access._open_channel('10.0.0.1', 80, ('127.0.0.1', 3)))
        self.assertTrue(old_jump.closed)
        self.assertTrue(old_node.closed)
        self.assertEqual(1, new_node.transport.calls)


if __name__ == '__main__':
    unittest.main()
