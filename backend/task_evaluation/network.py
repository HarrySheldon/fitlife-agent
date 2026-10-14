"""Worker-local network denial, with a narrow Windows self-pipe exception."""
import socket
from threading import local


def install_network_guard():
    from backend.task_evaluation.runner import NetworkAttempt
    permission = local()
    originals = {name: getattr(socket.socket, name) for name in ("connect", "connect_ex", "sendto")}
    original_pair = socket.socketpair
    original_create = socket.create_connection

    def permitted(address):
        return (getattr(permission, "selfpipe", False) and isinstance(address, tuple)
                and address and address[0] in {"127.0.0.1", "::1"})

    def pair(*args, **kwargs):
        permission.selfpipe = True
        try:
            return original_pair(*args, **kwargs)
        finally:
            permission.selfpipe = False

    def connect(sock, address):
        if permitted(address):
            return originals["connect"](sock, address)
        raise NetworkAttempt()

    def connect_ex(sock, address):
        if permitted(address):
            return originals["connect_ex"](sock, address)
        raise NetworkAttempt()

    def create(address, *args, **kwargs):
        if permitted(address):
            return original_create(address, *args, **kwargs)
        raise NetworkAttempt()

    def sendto(sock, data, *args):
        if args and permitted(args[-1]):
            return originals["sendto"](sock, data, *args)
        raise NetworkAttempt()

    socket.socketpair = pair
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.create_connection = create
    socket.socket.sendto = sendto

    def restore():
        socket.socketpair = original_pair
        socket.create_connection = original_create
        for name, method in originals.items():
            setattr(socket.socket, name, method)
    return restore
