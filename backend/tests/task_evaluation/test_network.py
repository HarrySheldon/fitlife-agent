import socket
import pytest
from backend.task_evaluation.network import install_network_guard
from backend.task_evaluation.runner import NetworkAttempt


def test_local_provider_is_denied_but_windows_selfpipe_works():
    restore = install_network_guard()
    try:
        with pytest.raises(NetworkAttempt):
            socket.create_connection(("127.0.0.1", 12345))
        with socket.socket() as sock:
            with pytest.raises(NetworkAttempt):
                sock.connect(("localhost", 12345))
            with pytest.raises(NetworkAttempt):
                sock.connect(("192.0.2.1", 12345))
            with pytest.raises(NetworkAttempt):
                sock.connect("local-provider.sock")
        first, second = socket.socketpair()
        try:
            first.send(b"safe")
            assert second.recv(4) == b"safe"
        finally:
            first.close()
            second.close()
    finally:
        restore()
