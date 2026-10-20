"""Cancelable asynchronous I/O behind the existing non-streaming SDK adapters.

The graph stays synchronous at its gateway boundary; the network operation does
not. Cancel schedules cancellation of the actual asyncio task. ``asyncio.run``
returns only after AsyncClient has finished its context-manager cleanup, so the
turn worker cannot publish cancellation while its local transport is still live.
"""
from __future__ import annotations

import asyncio
from threading import Lock

import httpx

from backend.application.ports.model_call_context import current_abort
from backend.domain.model_endpoint_policy import ModelEndpointPolicy


class AsyncCoachTransport(httpx.BaseTransport):
    def __init__(self, policy: ModelEndpointPolicy, *, transport_factory=None):
        self.policy = policy
        self.transport_factory = transport_factory or (lambda: httpx.AsyncHTTPTransport(retries=0))
        self._lock = Lock()
        self._closed = False
        self._loop = None
        self._task = None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.policy.validate_request_url(str(request.url))
        body = request.read()
        try:
            return asyncio.run(self._send(request, body))
        except asyncio.CancelledError:
            raise httpx.ReadError("Model request cancelled", request=request) from None

    async def _send(self, request: httpx.Request, body: bytes) -> httpx.Response:
        with self._lock:
            if self._closed:
                raise httpx.ReadError("Model transport closed", request=request)
            self._loop = asyncio.get_running_loop()
            self._task = asyncio.current_task()
        abort = current_abort.get()
        if abort is not None:
            abort.register(self.close)
        try:
            if abort is not None and abort.aborted:
                raise asyncio.CancelledError()
            async with httpx.AsyncClient(
                transport=self.transport_factory(), follow_redirects=False, trust_env=False,
            ) as client:
                outgoing = httpx.Request(
                    request.method, request.url, headers=request.headers,
                    content=body, extensions=request.extensions,
                )
                response = await client.send(outgoing)
                content = await response.aread()
                return httpx.Response(
                    response.status_code, headers=response.headers, content=content,
                    extensions=response.extensions,
                )
        finally:
            with self._lock:
                self._task = None
                self._loop = None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            loop, task = self._loop, self._task
        if loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass  # The request finished between the snapshot and scheduling.
