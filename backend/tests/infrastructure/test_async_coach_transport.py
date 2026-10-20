import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from threading import Thread
import socketserver

import httpx
import pytest

from backend.application.ports.model_call_context import AbortRegistry, current_abort
from backend.infrastructure.model_gateway.async_coach_gateway import AsyncCoachTransport


class Policy:
    def __init__(self):
        self.urls = []

    def validate_request_url(self, url):
        self.urls.append(url)


def test_cancel_waits_for_actual_async_cleanup_before_sync_caller_returns():
    started, cleaning, allow_close, closed = Event(), Event(), Event(), Event()

    class SlowTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            started.set()
            await asyncio.Event().wait()

        async def aclose(self):
            cleaning.set()
            while not allow_close.is_set():
                await asyncio.sleep(.005)
            closed.set()

    policy = Policy()
    abort = AbortRegistry()
    transport = AsyncCoachTransport(policy, transport_factory=SlowTransport)

    def run():
        token = current_abort.set(abort)
        try:
            with httpx.Client(transport=transport) as client:
                return client.post("https://model.invalid/test", json={})
        finally:
            current_abort.reset(token)

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(run)
        try:
            assert started.wait(2)
            abort.abort()
            assert cleaning.wait(2)
            assert not result.done()
            assert not closed.is_set()
            allow_close.set()
            with pytest.raises(httpx.ReadError):
                result.result(timeout=3)
            assert closed.is_set()
            assert policy.urls == ["https://model.invalid/test"]
        finally:
            allow_close.set()


def test_async_transport_preserves_non_streaming_response():
    class Success(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            assert await request.aread() == b'{"x":1}'
            return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=AsyncCoachTransport(Policy(), transport_factory=Success)) as client:
        assert client.post("https://model.invalid/test", json={"x": 1}).json() == {"ok": True}


def test_cancel_before_request_does_not_start_transport():
    abort = AbortRegistry()
    abort.abort()
    called = []
    token = current_abort.set(abort)
    try:
        transport = AsyncCoachTransport(Policy(), transport_factory=lambda: called.append(True))
        with httpx.Client(transport=transport) as client:
            with pytest.raises(httpx.ReadError):
                client.get("https://model.invalid/test")
        assert called == []
    finally:
        current_abort.reset(token)


def test_cancel_closes_a_real_loopback_http_connection():
    started, disconnected = Event(), Event()

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(5)
            self.request.recv(65536)
            started.set()
            try:
                while self.request.recv(4096):
                    pass
                disconnected.set()
            except ConnectionResetError:
                disconnected.set()

    with socketserver.ThreadingTCPServer(('127.0.0.1', 0), Handler) as server:
        server.daemon_threads = True
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        abort = AbortRegistry()

        def call():
            token = current_abort.set(abort)
            try:
                with httpx.Client(transport=AsyncCoachTransport(Policy())) as client:
                    client.get(f'http://127.0.0.1:{server.server_address[1]}/slow', timeout=5)
            finally:
                current_abort.reset(token)

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                result = executor.submit(call)
                assert started.wait(3)
                abort.abort()
                with pytest.raises(httpx.ReadError):
                    result.result(timeout=3)
                assert disconnected.wait(2), 'the actual TCP connection must close'
        finally:
            server.shutdown()
            thread.join(timeout=2)
