from __future__ import annotations

import json
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.api.coach_conversations import (
    get_coach_admission_service,
    get_coach_turn_service,
)
from backend.application.ports.coach_answer import CoachTurnAnswer
from backend.application.ports.model_call_context import current_abort
from backend.application.use_cases.coach_turns import CoachTurnService
from backend.config import get_settings
from backend.infrastructure.postgres.runtime import get_database
from backend.infrastructure.repositories.postgres_coach_conversation_repository import (
    PostgresCoachConversationRepository,
)
from backend.main import create_app

BASE = "/api/v1/coach"


class ControlledAnswer:
    def __init__(self, *, body: str = "Approved coaching answer paragraph.", review_status: str = "approved") -> None:
        self.started = Event()
        self.release = Event()
        self.aborted = Event()
        self.body = body
        self.review_status = review_status
        self.calls = 0

    def run(self, request) -> CoachTurnAnswer:
        self.calls += 1
        registry = current_abort.get()
        if registry is not None:
            registry.register(self.aborted.set)
        self.started.set()
        if request.progress_observer is not None:
            request.progress_observer({"step": "knowledge.search", "tool_name": "knowledge.search", "status": "started"})
            request.progress_observer({"step": "knowledge.search", "tool_name": "knowledge.search", "status": "succeeded"})
        while not self.release.wait(0.01):
            if self.aborted.is_set():
                raise RuntimeError("cancelled")
        return CoachTurnAnswer(
            answer_markdown=self.body,
            model="test-model",
            review_status=self.review_status,
        )


def _parse_sse_events(lines: list[str]) -> list[dict]:
    raw = "\n".join(lines)
    events = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        ev_id = 0
        ev_name = ""
        data_lines = []
        for line in block.splitlines():
            if not line or line.startswith(":"):
                continue
            if line.startswith("id:"):
                ev_id = int(line.split(":", 1)[1].strip())
            elif line.startswith("event:"):
                ev_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
        if ev_name and data_lines:
            events.append({"id": ev_id, "event": ev_name, "data": json.loads("\n".join(data_lines))})
    return events


@pytest.fixture
def sse_client(monkeypatch):
    data_dir = Path(".tmp") / "pytest-coach-sse" / uuid4().hex
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("COACH_CONVERSATIONS_ENABLED", "true")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


def _bind_service(client: TestClient, port: ControlledAnswer) -> CoachTurnService:
    svc = CoachTurnService(
        PostgresCoachConversationRepository(get_database()),
        port,
        lease_id="sse-test-lease",
    )
    client.app.dependency_overrides[get_coach_turn_service] = lambda: svc
    client.app.dependency_overrides[get_coach_admission_service] = lambda: svc
    return svc


def _account(client: TestClient) -> dict[str, str]:
    username = f"sse-{uuid4().hex[:10]}"
    resp = client.post(
        "/auth/register",
        json={"username": username, "password": "password123", "display_name": username},
    )
    assert resp.status_code == 200
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _conversation(client: TestClient, headers: dict[str, str]) -> str:
    resp = client.post(f"{BASE}/conversations", headers=headers, json={"title": "SSE"})
    assert resp.status_code == 200
    return resp.json()["data"]["conversation_id"]


def test_sse_live_stream_emits_progress_approved_answer_deltas_and_done(sse_client):
    port = ControlledAnswer(body="First segment of approved advice. Second segment of approved advice.")
    svc = _bind_service(sse_client, port)
    try:
        headers = _account(sse_client)
        other_headers = _account(sse_client)
        conv = _conversation(sse_client, headers)

        turn_resp = sse_client.post(
            f"{BASE}/conversations/{conv}/turns",
            headers={**headers, "Idempotency-Key": "sse-live-1"},
            json={"question": "How should I schedule squat sets?", "action": "chat", "surface": "today"},
        )
        assert turn_resp.status_code == 200
        turn_id = turn_resp.json()["data"]["turn_id"]
        assert port.started.wait(3)

        # Cross-user stream request is rejected with 404.
        assert sse_client.get(f"{BASE}/turns/{turn_id}/stream", headers=other_headers).status_code == 404

        def release_soon():
            port.started.wait(2)
            port.release.set()

        releaser = Thread(target=release_soon, daemon=True)
        releaser.start()
        with sse_client.stream("GET", f"{BASE}/turns/{turn_id}/stream", headers=headers) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            lines = list(resp.iter_lines())

        events = _parse_sse_events(lines)
        names = [ev["event"] for ev in events]
        assert "turn_status" in names
        assert "step_progress" in names
        assert "answer_delta" in names
        assert names[-1] == "turn_done"

        progress_stages = [ev["data"]["stage"] for ev in events if ev["event"] == "step_progress"]
        assert "knowledge_search" in progress_stages

        assembled = "".join(ev["data"]["delta"] for ev in events if ev["event"] == "answer_delta")
        assert assembled == port.body
        assert events[-1]["data"]["message"]["body"] == port.body

        # Replaying a terminal turn emits full approved sequence without re-running model,
        # and Last-Event-ID skips earlier frames.
        calls_before = port.calls
        with sse_client.stream("GET", f"{BASE}/turns/{turn_id}/stream", headers=headers) as replay_resp:
            assert replay_resp.status_code == 200
            replay_events = _parse_sse_events(list(replay_resp.iter_lines()))
        assert port.calls == calls_before
        assert replay_events[-1]["event"] == "turn_done"
        assert "".join(ev["data"]["delta"] for ev in replay_events if ev["event"] == "answer_delta") == port.body

        last_id = replay_events[-2]["id"]
        with sse_client.stream(
            "GET",
            f"{BASE}/turns/{turn_id}/stream",
            headers={**headers, "Last-Event-ID": str(last_id)},
        ) as tail_resp:
            tail_events = _parse_sse_events(list(tail_resp.iter_lines()))
        assert [ev["event"] for ev in tail_events] == ["turn_done"]
    finally:
        port.release.set()
        svc.close()


def test_sse_never_streams_unapproved_draft_on_safety_rejection(sse_client):
    secret_draft = "UNAPPROVED_UNSAFE_MEDICAL_ADVICE_SECRET"
    port = ControlledAnswer(body=secret_draft, review_status="rejected")
    port.release.set()
    svc = _bind_service(sse_client, port)
    try:
        headers = _account(sse_client)
        conv = _conversation(sse_client, headers)
        turn_id = sse_client.post(
            f"{BASE}/conversations/{conv}/turns",
            headers={**headers, "Idempotency-Key": "sse-rejected-1"},
            json={"question": "Should I train?", "action": "chat", "surface": "today"},
        ).json()["data"]["turn_id"]
        svc.wait(turn_id, timeout=5)

        with sse_client.stream("GET", f"{BASE}/turns/{turn_id}/stream", headers=headers) as resp:
            assert resp.status_code == 200
            raw = "\n".join(resp.iter_lines())
        events = _parse_sse_events(raw.splitlines())
        assert secret_draft not in raw
        assert not any(ev["event"] == "answer_delta" for ev in events)
        assert events[-1]["event"] == "turn_error"
        assert events[-1]["data"]["status"] == "failed"
        assert events[-1]["data"]["error_code"] == "ANSWER_NOT_APPROVED"
    finally:
        svc.close()


def test_sse_stream_closes_cleanly_on_turn_cancellation(sse_client):
    port = ControlledAnswer(body="Should never publish")
    svc = _bind_service(sse_client, port)
    try:
        headers = _account(sse_client)
        conv = _conversation(sse_client, headers)
        turn_id = sse_client.post(
            f"{BASE}/conversations/{conv}/turns",
            headers={**headers, "Idempotency-Key": "sse-cancel-1"},
            json={"question": "Plan a workout", "action": "chat", "surface": "today"},
        ).json()["data"]["turn_id"]
        assert port.started.wait(3)

        def cancel_soon():
            sse_client.post(f"{BASE}/turns/{turn_id}/cancel", headers=headers)

        Thread(target=cancel_soon, daemon=True).start()
        with sse_client.stream("GET", f"{BASE}/turns/{turn_id}/stream", headers=headers) as resp:
            events = _parse_sse_events(list(resp.iter_lines()))

        assert events[-1]["event"] == "turn_error"
        assert events[-1]["data"]["status"] == "cancelled"
        assert not any(ev["event"] == "answer_delta" for ev in events)
    finally:
        port.release.set()
        svc.close()
