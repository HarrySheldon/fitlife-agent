"""A slow streaming transport must not hold the settings request indefinitely."""
import json
import multiprocessing
from pathlib import Path
import time

import httpx
import pytest


def slow_stream_worker(channel, payload):
    class SlowBody(httpx.SyncByteStream):
        def __iter__(self):
            Path(payload["marker"]).write_text("started", encoding="utf-8")
            for _ in range(1000):
                time.sleep(0.05)
                yield b"."
    with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=SlowBody()))) as client:
        client.get("https://synthetic.example.com", timeout=0.1)
    channel.send_bytes(json.dumps({"ok": True, "value": None}).encode())


def wire_worker(channel, payload):
    channel.send_bytes(json.dumps(payload["message"]).encode())
    channel.close()


def test_deadline_terminates_slow_stream_and_leaves_no_child_process(tmp_path):
    from backend.infrastructure.model_gateway.preview_process import ProbeProcessRunner

    original = {child.pid for child in multiprocessing.active_children()}
    marker = tmp_path / "stream-started.txt"
    runner = ProbeProcessRunner(worker=slow_stream_worker)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        runner.run({"marker": str(marker)}, seconds=3)
    elapsed = time.monotonic() - started
    assert marker.exists(), "The synthetic streaming response must actually start"
    assert elapsed < 5
    assert {child.pid for child in multiprocessing.active_children()} == original


def test_success_and_sanitized_failure_cross_process_contract():
    from backend.domain.errors import ApplicationError
    from backend.infrastructure.model_gateway.preview_process import ProbeProcessRunner
    runner = ProbeProcessRunner(worker=wire_worker)
    assert runner.run({"message": {"ok": True, "value": ["synthetic"]}}, seconds=5) == ["synthetic"]
    with pytest.raises(ApplicationError) as rejected:
        runner.run({"message": {"ok": False, "code": "MODEL_AUTH_FAILED", "status": 502}}, seconds=5)
    assert rejected.value.code == "MODEL_AUTH_FAILED"
