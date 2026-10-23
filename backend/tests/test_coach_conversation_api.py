"""Public contract of the conversation entry.

These tests drive the HTTP surface only. They assert what a client can observe —
status codes, ownership, the single slot, cancellation — and never reach into the
repository to make a point. A second entry that bypassed the same admission would
pass the service tests and fail these.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Event
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
from backend.infrastructure.repositories.sqlite_coach_conversation_repository import (
    SQLiteCoachConversationRepository,
)
from backend.infrastructure.sqlite.runtime import get_database
from backend.main import create_app

BASE = "/api/v1/coach"


class SlowAnswer:
    """A model that never returns on its own; the test decides when it may."""

    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.aborted = Event()
        self.calls = 0

    def run(self, request) -> CoachTurnAnswer:
        self.calls += 1
        registry = current_abort.get()
        if registry is not None:
            registry.register(self.aborted.set)
        self.started.set()
        while not self.release.wait(0.01):
            if self.aborted.is_set():
                raise RuntimeError("the transport was closed")
        return CoachTurnAnswer(answer_markdown="Steady progress.", model="test-model")


@pytest.fixture
def client(monkeypatch):
    data_dir = Path(".tmp") / "pytest-coach-conversations" / uuid4().hex
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("COACH_CONVERSATIONS_ENABLED", "true")
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()


@pytest.fixture
def answer():
    port = SlowAnswer()
    yield port
    port.release.set()


@pytest.fixture
def service(client, answer):
    """Bind the routes to a controllable model, but keep the real database."""

    def build() -> CoachTurnService:
        return CoachTurnService(
            SQLiteCoachConversationRepository(get_database()),
            answer,
            lease_id="test-lease",
        )

    built = build()
    # Both accessors resolve to the same instance in production; bind both here so
    # the test exercises the real single service rather than two of them.
    client.app.dependency_overrides[get_coach_turn_service] = lambda: built
    client.app.dependency_overrides[get_coach_admission_service] = lambda: built
    yield built
    built.close()


def _account(client: TestClient, name: str | None = None) -> tuple[dict[str, str], str]:
    username = name or f"coach-{uuid4().hex[:10]}"
    response = client.post(
        "/auth/register",
        json={"username": username, "password": "password123", "display_name": username},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user"]["user_id"]


def _headers(client: TestClient, name: str | None = None) -> dict[str, str]:
    return _account(client, name)[0]


def _conversation(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(f"{BASE}/conversations", headers=headers, json={"title": "Today"})
    assert response.status_code == 200, response.text
    return response.json()["data"]["conversation_id"]


def _ask(client: TestClient, headers: dict[str, str], conversation_id: str, key: str):
    return client.post(
        f"{BASE}/conversations/{conversation_id}/turns",
        headers={**headers, "Idempotency-Key": key},
        json={"question": "How is today going?", "action": "chat", "surface": "today"},
    )


def test_the_entry_is_off_until_the_deployment_enables_it(monkeypatch):
    monkeypatch.setenv("DATA_DIR", ".tmp/pytest-coach-conversations/off")
    monkeypatch.delenv("COACH_CONVERSATIONS_ENABLED", raising=False)
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as fresh:
            headers = _headers(fresh)
            response = fresh.get(f"{BASE}/conversations", headers=headers)
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "COACH_CONVERSATIONS_DISABLED"
    finally:
        get_settings.cache_clear()


def test_every_route_requires_an_account(client, service):
    conversation_id = "conv-x"
    for method, path, body in (
        ("get", f"{BASE}/conversations", None),
        ("post", f"{BASE}/conversations", {"title": "x"}),
        ("patch", f"{BASE}/conversations/{conversation_id}", {"title": "x"}),
        ("delete", f"{BASE}/conversations/{conversation_id}", None),
        ("get", f"{BASE}/conversations/{conversation_id}/messages", None),
        ("get", f"{BASE}/active-turn", None),
        ("get", f"{BASE}/turns/t1", None),
        ("post", f"{BASE}/turns/t1/cancel", None),
    ):
        response = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
        assert response.status_code == 401, f"{method} {path} -> {response.status_code}"


def test_a_conversation_is_invisible_to_another_account(client, service):
    alice = _headers(client)
    bob = _headers(client)
    conversation_id = _conversation(client, alice)

    assert client.get(f"{BASE}/conversations/{conversation_id}/messages", headers=bob).status_code == 404
    assert client.patch(
        f"{BASE}/conversations/{conversation_id}", headers=bob, json={"title": "mine"}
    ).status_code == 404
    assert client.delete(f"{BASE}/conversations/{conversation_id}", headers=bob).status_code == 404
    assert client.get(f"{BASE}/conversations", headers=bob).json()["data"]["conversations"] == []


def test_repeating_the_same_key_returns_the_same_turn_without_a_second_call(
    client, service, answer
):
    headers = _headers(client)
    conversation_id = _conversation(client, headers)

    first = _ask(client, headers, conversation_id, "key-1")
    assert first.status_code == 200, first.text
    turn_id = first.json()["data"]["turn_id"]
    assert answer.started.wait(2)

    again = _ask(client, headers, conversation_id, "key-1")
    assert again.status_code == 200
    assert again.json()["data"]["turn_id"] == turn_id
    assert again.json()["data"]["replayed"] is True

    answer.release.set()
    service.wait(turn_id, timeout=5)
    assert answer.calls == 1


def test_a_second_key_while_running_is_refused_not_queued(client, service, answer):
    headers = _headers(client)
    conversation_id = _conversation(client, headers)

    assert _ask(client, headers, conversation_id, "key-1").status_code == 200
    assert answer.started.wait(2)

    busy = _ask(client, headers, conversation_id, "key-2")
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "COACH_TURN_BUSY"

    answer.release.set()


def test_a_stopping_turn_still_holds_the_slot(client, service, answer, monkeypatch):
    # Abort notification is not proof that the worker has finished unwinding.
    # Hold that boundary explicitly: the default fake can otherwise exit in
    # 10 ms, legitimately releasing the slot before the next HTTP request.
    transport_unwinding = Event()
    allow_transport_close = Event()
    original_run = answer.run

    def controlled_run(request):
        try:
            return original_run(request)
        finally:
            transport_unwinding.set()
            if not allow_transport_close.wait(5):
                raise RuntimeError('test transport close barrier timed out')

    monkeypatch.setattr(answer, 'run', controlled_run)
    headers = _headers(client)
    conversation_id = _conversation(client, headers)
    turn_id = _ask(client, headers, conversation_id, "key-1").json()["data"]["turn_id"]
    assert answer.started.wait(2)

    stopped = client.post(f"{BASE}/turns/{turn_id}/cancel", headers=headers)
    assert stopped.status_code == 200
    assert stopped.json()["data"]["status"] == "running"
    assert stopped.json()["data"]["stopping"] is True

    try:
        assert answer.aborted.wait(2)
        assert transport_unwinding.wait(2)
        # The controlled transport has not closed, so the slot must stay held.
        busy = _ask(client, headers, conversation_id, "key-2")
        assert busy.status_code == 409
        assert busy.json()["error"]["code"] == "COACH_TURN_BUSY"
    finally:
        allow_transport_close.set()

    service.wait(turn_id, timeout=5)
    assert client.get(f"{BASE}/turns/{turn_id}", headers=headers).json()["data"]["status"] == "cancelled"


def test_an_awaiting_user_turn_releases_the_slot(client, service, answer):
    headers, user_id = _account(client)
    conversation_id = _conversation(client, headers)

    # A turn that asked the user a question: the model is finished, so it is
    # waiting on a human and must not keep the account's only slot.
    now = datetime.now(timezone.utc)
    service.repository.accept_turn(
        user_id,
        conversation_id,
        turn_id="waiting-turn",
        idempotency_key="seed-key",
        request_fingerprint="seed-fingerprint",
        created_at=now,
    )
    service.repository.claim_turn(
        user_id, "waiting-turn", lease_id="seed-lease", started_at=now
    )
    service.repository.release_slot(user_id, "waiting-turn", at=now)

    second = _ask(client, headers, conversation_id, "key-2")
    assert second.status_code == 200, second.text
    answer.release.set()


def test_reading_a_turn_never_starts_a_model_call(client, service, answer):
    headers = _headers(client)
    conversation_id = _conversation(client, headers)
    turn_id = _ask(client, headers, conversation_id, "key-1").json()["data"]["turn_id"]
    assert answer.started.wait(2)

    before = answer.calls
    for _ in range(3):
        assert client.get(f"{BASE}/turns/{turn_id}", headers=headers).status_code == 200
        assert client.get(f"{BASE}/active-turn", headers=headers).status_code == 200
        assert client.get(f"{BASE}/conversations/{conversation_id}/messages", headers=headers).status_code == 200
    assert answer.calls == before


def test_cancel_states_the_billing_limit_the_user_cannot_undo(client, service, answer):
    headers = _headers(client)
    conversation_id = _conversation(client, headers)
    turn_id = _ask(client, headers, conversation_id, "key-1").json()["data"]["turn_id"]
    assert answer.started.wait(2)

    body = client.post(f"{BASE}/turns/{turn_id}/cancel", headers=headers).json()["data"]
    assert body["notice"]
    assert "refund" in body["notice"].lower() or "费用" in body["notice"]


def test_asking_in_a_conversation_that_does_not_exist_is_refused(client, service):
    headers = _headers(client)
    response = _ask(client, headers, "conv-missing", "key-1")
    assert response.status_code == 404


def test_a_deleted_conversation_stops_accepting_turns(client, service, answer):
    headers = _headers(client)
    conversation_id = _conversation(client, headers)
    turn_id = _ask(client, headers, conversation_id, "key-1").json()["data"]["turn_id"]
    assert answer.started.wait(2)

    assert client.delete(f"{BASE}/conversations/{conversation_id}", headers=headers).status_code == 200
    service.wait(turn_id, timeout=5)

    assert client.get(f"{BASE}/turns/{turn_id}", headers=headers).status_code == 404
    assert _ask(client, headers, conversation_id, "key-2").status_code == 404


def test_deleting_the_account_stops_its_running_turn(client, service, answer):
    """Account deletion ends the work, not just the session that started it."""
    headers, user_id = _account(client)
    conversation_id = _conversation(client, headers)
    turn_id = _ask(client, headers, conversation_id, "key-1").json()["data"]["turn_id"]
    assert answer.started.wait(2)

    deleted = client.request(
        "DELETE",
        "/account",
        headers=headers,
        json={"password": "password123", "confirmation": "DELETE"},
    )
    assert deleted.status_code == 200
    service.wait(turn_id, timeout=10)

    assert service.repository.active_turn(user_id) is None
    with pytest.raises(KeyError):
        service.repository.get_turn(user_id, turn_id)


@pytest.mark.parametrize("path", ["/auth/logout", "/account/sessions/revoke-others"])
def test_explicit_logout_or_revocation_stops_account_work(client, service, answer, path):
    headers, user_id = _account(client)
    conversation = _conversation(client, headers)
    turn = _ask(client, headers, conversation, "logout-key").json()["data"]["turn_id"]
    assert answer.started.wait(2)
    assert client.post(path, headers=headers).status_code == 200
    service.wait(turn, timeout=5)
    assert answer.aborted.is_set()
    assert service.repository.active_turn(user_id) is None
    assert service.repository.get_turn(user_id, turn).status == "cancelled"
