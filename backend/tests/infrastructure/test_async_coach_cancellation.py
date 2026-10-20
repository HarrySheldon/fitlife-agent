"""Cancellation must close the transport, not just flip a flag.

A cancel that only sets an event leaves the synchronous model call alive: the
thread keeps its socket and the account keeps its only execution slot until the
provider answers. These tests make that visible by driving a transport that
blocks until someone closes it, and they check the three things that prove the
close is real:

* the transport records ``started`` and ``closed``;
* the slot is still taken between the cancel and the terminal publish;
* nothing the late call produced is ever written.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from threading import Event, Thread

import httpx
import pytest

from backend.agent import graph
from backend.agent.policy import RuntimePolicy
from backend.agent.route_contract import PlannerRoute
from backend.agent.runtime import RunCancelled, RuntimeContext
from backend.application.ports.coach_answer import CoachTurnAnswer
from backend.application.ports.model_call_context import AbortRegistry, current_abort
from backend.application.use_cases.coach_turns import CoachTurnService
from backend.infrastructure.model_gateway.openai_responses import OpenAIResponsesAdapter
from backend.infrastructure.repositories.sqlite_coach_conversation_repository import (
    SQLiteCoachConversationRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


class BlockingTransport(httpx.BaseTransport):
    """A request that never completes until the client is closed."""

    def __init__(self) -> None:
        self.started = Event()
        self.closed = Event()
        self.requests = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        self.started.set()
        if not self.closed.wait(10):
            raise AssertionError("the transport was never closed")
        raise httpx.ReadError("the transport was closed", request=request)

    def close(self) -> None:
        self.closed.set()


class _Parsed:
    def __init__(self, payload) -> None:
        self.output = [
            type(
                "Output",
                (),
                {
                    "type": "message",
                    "content": [
                        type("Item", (), {"type": "output_text", "parsed": payload})()
                    ],
                },
            )()
        ]


class _Text:
    def __init__(self, text: str) -> None:
        self.output_text = text
        self.model = "test-model"
        self.usage = None


class FakeSdk:
    """OpenAI-shaped client whose every call goes through a real httpx client."""

    def __init__(self, transport: BlockingTransport) -> None:
        self.http = httpx.Client(transport=transport)
        self.responses = self

    def parse(self, **_kwargs):
        self._block()
        return _Parsed(PlannerRoute(intent="meal_analysis", needs_meal_analysis=True))

    def create(self, **_kwargs):
        self._block()
        return _Text("A late answer that must never be stored.")

    def _block(self) -> None:
        self.http.post("https://api.openai.com/v1/responses", json={})

    def close(self) -> None:
        self.http.close()


def _gateway(transport: BlockingTransport) -> OpenAIResponsesAdapter:
    return OpenAIResponsesAdapter(client=FakeSdk(transport), model="test-model")


def _run_while_aborting(call) -> tuple[list[BaseException], BlockingTransport, AbortRegistry]:
    """Start ``call`` in a worker, abort once it is blocked, and return the outcome."""
    registry = AbortRegistry()
    errors: list[BaseException] = []

    def work() -> None:
        token = current_abort.set(registry)
        try:
            call(registry)
        except BaseException as error:  # noqa: BLE001 - the test asserts on the type
            errors.append(error)
        finally:
            current_abort.reset(token)

    thread = Thread(target=work)
    thread.start()
    return errors, thread, registry


@pytest.mark.parametrize(
    "call_name",
    ["planner", "writer", "reviewer"],
)
def test_every_model_stage_closes_its_transport_on_cancel(call_name):
    transport = BlockingTransport()
    gateway = _gateway(transport)

    def call(registry: AbortRegistry) -> None:
        graph._register_abort(gateway)
        if call_name == "planner":
            gateway.plan_route("How is today?")
        elif call_name == "writer":
            gateway.write_answer({"question": "How is today?"})
        else:
            gateway.parse_structured(
                instructions="review",
                input_text="draft",
                response_model=PlannerRoute,
            )

    errors, thread, registry = _run_while_aborting(call)
    assert transport.started.wait(5), f"{call_name} never reached the transport"
    assert not transport.closed.is_set()

    assert registry.abort() == 1
    thread.join(10)
    assert not thread.is_alive(), f"{call_name} kept its thread alive after the close"
    assert transport.closed.is_set()
    assert errors, f"{call_name} returned an answer after its transport was closed"
    assert transport.requests == 1


def test_a_cancel_during_a_retry_wait_starts_no_second_attempt():
    cancel_event = Event()
    registry = AbortRegistry()
    registry.register(cancel_event.set)

    waiting = Event()

    def sleeper(_delay: float) -> None:
        waiting.set()
        assert cancel_event.wait(10)

    context = RuntimeContext(
        policy=RuntimePolicy(), sleeper=sleeper, cancel_event=cancel_event
    )
    attempts: list[int] = []

    async def operation():
        attempts.append(1)
        raise TimeoutError("the provider timed out")

    async def run() -> None:
        token = current_abort.set(registry)
        try:
            await context._invoke("write_answer_model", operation, replay="safe", is_tool=True)
        finally:
            current_abort.reset(token)

    errors: list[BaseException] = []

    def work() -> None:
        try:
            asyncio.run(run())
        except BaseException as error:  # noqa: BLE001 - the test asserts on the type
            errors.append(error)

    thread = Thread(target=work)
    thread.start()
    assert waiting.wait(10), "the retry never reached its wait"
    registry.abort()
    thread.join(10)

    assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], RunCancelled)
    assert attempts == [1], "a cancel during the wait must not replay the call"


class GatedRepository(SQLiteCoachConversationRepository):
    """Holds publication open so the slot's state can be observed mid-cancel."""

    gate = Event()

    def publish_turn(self, *args, **kwargs):
        self.gate.wait(5)
        return super().publish_turn(*args, **kwargs)


class GatewayAnswer:
    """The narrow port, wired the way the graph wires it."""

    def __init__(self, gateway: OpenAIResponsesAdapter) -> None:
        self.gateway = gateway

    def run(self, request) -> CoachTurnAnswer:
        graph._register_abort(self.gateway)
        text = self.gateway.write_answer({"question": request.question})
        return CoachTurnAnswer(answer_markdown=text, model="test-model")


def test_the_slot_survives_the_cancel_until_the_transport_closes(tmp_path):
    database = SQLiteDatabase(tmp_path / "coach.sqlite")
    run_migrations(database, RECORDS_MIGRATIONS)
    repository = GatedRepository(database)
    repository.create_conversation(
        "alice", conversation_id="c1", title="Today", created_at=NOW
    )

    transport = BlockingTransport()
    service = CoachTurnService(
        repository, GatewayAnswer(_gateway(transport)), clock=lambda: NOW, lease_id="w1"
    )
    submission = service.submit(
        "alice", "c1", idempotency_key="k1", question="How is today?", action="chat", surface="today"
    )
    turn_id = submission.turn.turn_id
    try:
        assert transport.started.wait(5)
        assert repository.active_turn("alice") is not None

        stopped = service.cancel("alice", turn_id)
        assert stopped.status == "running"
        assert stopped.cancel_requested_at is not None

        # The transport is closed, but the turn has not published yet: the slot is
        # still taken, so nothing else can start against this account.
        assert transport.closed.is_set()
        assert repository.active_turn("alice") is not None

        GatedRepository.gate.set()
        service.wait(turn_id, timeout=10)

        assert repository.get_turn("alice", turn_id).status == "cancelled"
        assert repository.active_turn("alice") is None
        assert [m.role for m in repository.list_messages("alice", "c1", now=NOW)] == ["user"]
    finally:
        GatedRepository.gate.set()
        transport.closed.set()
        service.close()


def test_a_late_answer_is_discarded_rather_than_stored(tmp_path):
    database = SQLiteDatabase(tmp_path / "coach.sqlite")
    run_migrations(database, RECORDS_MIGRATIONS)
    repository = SQLiteCoachConversationRepository(database)
    repository.create_conversation(
        "alice", conversation_id="c1", title="Today", created_at=NOW
    )

    transport = BlockingTransport()
    gateway = _gateway(transport)
    # A transport that ignores the close and returns text anyway: the worst case a
    # provider can produce, and the one the repository has to reject on its own.
    late = CoachTurnAnswer(answer_markdown="Late answer", model="test-model")

    class IgnoresClose(GatewayAnswer):
        def run(self, request) -> CoachTurnAnswer:
            graph._register_abort(self.gateway)
            try:
                self.gateway.write_answer({"question": request.question})
            except Exception:
                pass
            return late

    service = CoachTurnService(
        repository, IgnoresClose(gateway), clock=lambda: NOW, lease_id="w1"
    )
    turn_id = service.submit(
        "alice", "c1", idempotency_key="k1", question="How is today?", action="chat", surface="today"
    ).turn.turn_id
    try:
        assert transport.started.wait(5)
        service.cancel("alice", turn_id)
        service.wait(turn_id, timeout=10)

        turn = repository.get_turn("alice", turn_id)
        assert turn.status == "cancelled"
        assert [m.role for m in repository.list_messages("alice", "c1", now=NOW)] == ["user"]
        # Failed/cancelled attempts retain only their original safe retry context,
        # never the late model result or an approval receipt.
        import json

        receipt = json.loads(turn.receipt_json)
        assert set(receipt) == {"context"}
        assert receipt["context"]["action"] == "chat"
        assert "Late answer" not in turn.receipt_json
    finally:
        transport.closed.set()
        service.close()
