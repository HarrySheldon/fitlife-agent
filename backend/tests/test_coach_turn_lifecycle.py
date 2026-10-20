"""Turn lifecycle through the service: admission, cancel, publication.

The fake answer port watches the abort registry the way a real gateway watches its
socket: when the run is aborted it stops waiting and raises. That keeps these tests
about the service's decisions, while the socket-level proof lives in
``infrastructure/test_async_coach_cancellation.py``.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
import time

import pytest

from backend.application.ports.coach_answer import CoachTurnAnswer
from backend.application.ports.model_call_context import current_abort
from backend.application.use_cases.coach_turns import CoachTurnService, LegacyAnswerDiscarded
from backend.domain.coach_turn import TurnNotCancellable, TurnSlotBusy
from backend.infrastructure.repositories.sqlite_coach_conversation_repository import (
    SQLiteCoachConversationRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


class CoachTurnAborted(RuntimeError):
    pass


class InstantAnswer:
    def __init__(self, text="Steady."):
        self.text = text
        self.calls = 0

    def run(self, request):
        self.calls += 1
        return CoachTurnAnswer(answer_markdown=self.text, model="test-model")


class BlockingAnswer:
    """Waits until released, or until the abort registry closes the transport.

    ``close_delay`` models a transport that takes a moment to unwind after
    ``close()``; the slot must stay taken for that whole window.
    """

    def __init__(self, close_delay=0.0):
        self.started = Event()
        self.release = Event()
        self.aborted = Event()
        self.close_delay = close_delay
        self.calls = 0

    def run(self, request):
        self.calls += 1
        # Per-call state: two accounts may run at once, and one account's abort
        # must not stop the other's answer.
        aborted = Event()
        registry = current_abort.get()
        if registry is not None:
            registry.register(aborted.set)
            registry.register(self.aborted.set)
        self.started.set()
        while not self.release.wait(0.01):
            if aborted.is_set():
                if self.close_delay:
                    time.sleep(self.close_delay)
                raise CoachTurnAborted("the transport was closed")
        if aborted.is_set():
            raise CoachTurnAborted("the transport was closed")
        return CoachTurnAnswer(answer_markdown="Late answer", model="test-model")


class FailingAnswer:
    def run(self, request):
        raise ValueError("provider exploded")


@pytest.mark.parametrize("mode,ceiling", [("brief", 1200), ("detailed", 3000)])
def test_overlong_final_answer_is_not_truncated_or_published(repository, mode, ceiling):
    _conversation(repository)
    service = _service(repository, InstantAnswer("x" * (ceiling + 1)))
    try:
        accepted = service.submit("alice", "c1", idempotency_key="long", question="Explain protein",
            action="chat", surface="today", answer_mode=mode)
        service.wait(accepted.turn.turn_id, timeout=5)
        turn = repository.get_turn("alice", accepted.turn.turn_id)
        assert turn.status == "failed"
        assert turn.error_code == "COACH_ANSWER_TOO_LONG"
        assert [item.role for item in repository.list_messages("alice", "c1", now=NOW)] == ["user"]
    finally:
        service.close()


@pytest.fixture
def repository(tmp_path):
    database = SQLiteDatabase(tmp_path / "coach.sqlite")
    run_migrations(database, RECORDS_MIGRATIONS)
    return SQLiteCoachConversationRepository(database)


def _conversation(repository, *, user="alice", conversation="c1"):
    try:
        return repository.get_conversation(user, conversation)
    except KeyError:
        return repository.create_conversation(
            user, conversation_id=conversation, title="Today", created_at=NOW
        )


def _service(repository, answer, *, workers=2):
    executor = ThreadPoolExecutor(max_workers=workers)
    return CoachTurnService(
        repository, answer, clock=lambda: NOW, lease_id="worker-1", executor=executor
    )


def _submit(service, *, user="alice", conversation="c1", key="k1", question="How is today?"):
    _conversation(service.repository, user=user, conversation=conversation)
    return service.submit(
        user,
        conversation,
        idempotency_key=key,
        question=question,
        action="chat",
        surface="coach",
    )


# -- admission -------------------------------------------------------------


def test_submit_returns_the_turn_before_the_answer_exists(repository):
    answer = BlockingAnswer()
    service = _service(repository, answer)
    try:
        submission = _submit(service)
        assert submission.replayed is False
        assert submission.turn.status == "queued"
        assert answer.started.wait(2)

        # The question is durable while the model is still thinking.
        messages = repository.list_messages("alice", "c1", now=NOW)
        assert [message.role for message in messages] == ["user"]
        assert messages[0].body == "How is today?"
    finally:
        answer.release.set()
        service.close()


def test_a_completed_turn_stores_the_answer_and_releases_the_slot(repository):
    service = _service(repository, InstantAnswer())
    try:
        submission = _submit(service)
        service.wait(submission.turn.turn_id, timeout=5)

        turn = repository.get_turn("alice", submission.turn.turn_id)
        assert turn.status == "succeeded"
        assert turn.receipt_json is not None
        assert repository.active_turn("alice") is None
        messages = repository.list_messages("alice", "c1", now=NOW)
        assert [(m.role, m.body) for m in messages] == [
            ("user", "How is today?"),
            ("coach", "Steady."),
        ]
    finally:
        service.close()


def test_repeating_a_key_does_not_start_a_second_call(repository):
    answer = InstantAnswer()
    service = _service(repository, answer)
    try:
        first = _submit(service, key="k1")
        service.wait(first.turn.turn_id, timeout=5)

        again = _submit(service, key="k1")

        assert again.replayed is True
        assert again.turn.turn_id == first.turn.turn_id
        assert answer.calls == 1
    finally:
        service.close()


def test_a_different_key_is_refused_while_the_slot_is_taken(repository):
    answer = BlockingAnswer()
    service = _service(repository, answer)
    try:
        _submit(service, key="k1")
        assert answer.started.wait(2)

        with pytest.raises(TurnSlotBusy):
            _submit(service, key="k2")
    finally:
        answer.release.set()
        service.close()


def test_a_failing_answer_ends_the_turn_as_failed_and_frees_the_slot(repository):
    service = _service(repository, FailingAnswer())
    try:
        submission = _submit(service)
        service.wait(submission.turn.turn_id, timeout=5)

        turn = repository.get_turn("alice", submission.turn.turn_id)
        assert turn.status == "failed"
        assert turn.error_code == "COACH_TURN_FAILED"
        assert repository.active_turn("alice") is None
        # A failed turn stores no coach text.
        assert [m.role for m in repository.list_messages("alice", "c1", now=NOW)] == ["user"]
    finally:
        service.close()


# -- cancellation ----------------------------------------------------------


def test_cancel_stops_the_answer_and_stores_nothing_late(repository):
    answer = BlockingAnswer()
    service = _service(repository, answer)
    try:
        submission = _submit(service)
        assert answer.started.wait(2)

        stopping = service.cancel("alice", submission.turn.turn_id)
        assert stopping.status == "running"
        assert stopping.cancel_requested_at == NOW

        # The abort closed the transport, so the worker can now return.
        assert answer.aborted.is_set()
        service.wait(submission.turn.turn_id, timeout=5)

        turn = repository.get_turn("alice", submission.turn.turn_id)
        assert turn.status == "cancelled"
        assert repository.active_turn("alice") is None
        assert [m.role for m in repository.list_messages("alice", "c1", now=NOW)] == ["user"]
    finally:
        answer.release.set()
        service.close()


def test_the_slot_stays_taken_until_the_transport_closes(repository):
    answer = BlockingAnswer(close_delay=0.5)
    service = _service(repository, answer)
    try:
        submission = _submit(service)
        assert answer.started.wait(2)
        service.cancel("alice", submission.turn.turn_id)

        # close() returned, but the request is still unwinding, so the slot is held.
        assert repository.active_turn("alice") is not None
        with pytest.raises(TurnSlotBusy):
            _submit(service, key="k2")

        service.wait(submission.turn.turn_id, timeout=10)
        assert repository.active_turn("alice") is None
    finally:
        answer.release.set()
        service.close()


def test_cancelling_twice_is_harmless(repository):
    answer = BlockingAnswer()
    service = _service(repository, answer)
    try:
        submission = _submit(service)
        assert answer.started.wait(2)
        first = service.cancel("alice", submission.turn.turn_id)
        second = service.cancel("alice", submission.turn.turn_id)
        assert second.cancel_requested_at == first.cancel_requested_at
        service.wait(submission.turn.turn_id, timeout=5)
    finally:
        answer.release.set()
        service.close()


def test_cancelling_a_finished_turn_is_refused(repository):
    service = _service(repository, InstantAnswer())
    try:
        submission = _submit(service)
        service.wait(submission.turn.turn_id, timeout=5)
        with pytest.raises(TurnNotCancellable):
            service.cancel("alice", submission.turn.turn_id)
    finally:
        service.close()


def test_a_waiting_turn_is_cancelled_without_closing_anything(repository):
    answer = BlockingAnswer()
    service = _service(repository, answer)
    try:
        submission = _submit(service)
        assert answer.started.wait(2)
        repository.release_slot("alice", submission.turn.turn_id, at=NOW)

        cancelled = service.cancel("alice", submission.turn.turn_id)
        assert cancelled.status == "cancelled"
        # Releasing the worker afterwards must not revive the turn.
        answer.release.set()
        service.wait(submission.turn.turn_id, timeout=5)
        assert repository.get_turn("alice", submission.turn.turn_id).status == "cancelled"
    finally:
        answer.release.set()
        service.close()


def test_deleting_a_chat_stops_its_running_turn_first(repository):
    answer = BlockingAnswer()
    service = _service(repository, answer)
    try:
        submission = _submit(service)
        assert answer.started.wait(2)

        assert service.delete_conversation("alice", "c1") is True
        service.wait(submission.turn.turn_id, timeout=5)

        # The chat is gone, so its turn is gone with it: a deleted conversation
        # must not keep answering through a status read.
        with pytest.raises(KeyError):
            repository.get_turn("alice", submission.turn.turn_id)
        with pytest.raises(KeyError):
            repository.get_conversation("alice", "c1")
        assert repository.active_turn("alice") is None
    finally:
        answer.release.set()
        service.close()


def test_deleting_chat_keeps_slot_until_worker_has_finished_cleanup(repository):
    class SlowCleanup:
        def __init__(self):
            self.started = Event()
            self.stopping = Event()
            self.closed = Event()

        def run(self, request):
            current_abort.get().register(self.stopping.set)
            self.started.set()
            assert self.closed.wait(5), "test must release cleanup"
            raise CoachTurnAborted("transport cleanup completed")

    answer = SlowCleanup()
    service = _service(repository, answer)
    try:
        submission = _submit(service)
        assert answer.started.wait(2)
        assert service.delete_conversation("alice", "c1")
        assert answer.stopping.is_set()
        # Account deletion/revocation uses an internal owner-scoped cancellation
        # path; hiding the deleted transcript must not make this raise KeyError.
        stopped = service.cancel_active_for_account("alice")
        assert stopped.turn_id == submission.turn.turn_id
        with pytest.raises(KeyError):
            repository.get_conversation("alice", "c1")
        with pytest.raises(TurnSlotBusy):
            _submit(service, conversation="c2", key="k2")
        answer.closed.set()
        service.wait(submission.turn.turn_id, timeout=5)
        assert repository.active_turn("alice") is None
        next_turn = _submit(service, conversation="c2", key="k2")
        service.wait(next_turn.turn.turn_id, timeout=5)
    finally:
        answer.closed.set()
        service.close()


def test_logging_out_stops_the_account_turn(repository):
    answer = BlockingAnswer()
    service = _service(repository, answer)
    try:
        submission = _submit(service)
        assert answer.started.wait(2)

        stopping = service.cancel_active_for_account("alice")
        assert stopping.turn_id == submission.turn.turn_id
        service.wait(submission.turn.turn_id, timeout=5)
        assert repository.get_turn("alice", submission.turn.turn_id).status == "cancelled"
    finally:
        answer.release.set()
        service.close()


def test_cancelling_one_account_does_not_touch_another(repository):
    answer = BlockingAnswer()
    service = _service(repository, answer)
    try:
        alice = _submit(service, user="alice", conversation="c1", key="k1")
        bob = _submit(service, user="bob", conversation="c2", key="k2")
        assert answer.started.wait(2)

        service.cancel("alice", alice.turn.turn_id)
        service.wait(alice.turn.turn_id, timeout=5)

        assert repository.get_turn("bob", bob.turn.turn_id).status in {"queued", "running"}
        assert repository.active_turn("bob") is not None
    finally:
        answer.release.set()
        service.close()


# -- legacy quick actions --------------------------------------------------


def test_a_quick_action_takes_the_same_slot(repository):
    answer = InstantAnswer()
    service = _service(repository, answer)
    try:
        lease = service.begin_legacy(
            "alice", question="Explain today", action="explain_today", surface="today"
        )
        assert lease.status == "running"

        with pytest.raises(TurnSlotBusy):
            _submit(service, key="k2")

        assert service.finish_legacy(
            "alice", lease, answer_markdown="Done.", model="test-model"
        )
        assert repository.active_turn("alice") is None
    finally:
        service.close()


def test_a_quick_action_is_not_listed_as_a_chat(repository):
    service = _service(repository, InstantAnswer())
    try:
        lease = service.begin_legacy(
            "alice", question="Explain today", action="explain_today", surface="today"
        )
        service.finish_legacy("alice", lease, answer_markdown="Done.", model="m")

        assert repository.list_conversations("alice") == ()
        exported = repository.export_conversations("alice", max_bytes=1_000_000, now=NOW)
        assert b"system:" not in exported
    finally:
        service.close()


def test_a_failed_quick_action_frees_the_slot(repository):
    service = _service(repository, InstantAnswer())
    try:
        lease = service.begin_legacy(
            "alice", question="Explain today", action="explain_today", surface="today"
        )
        service.fail_legacy("alice", lease, error_code="MODEL_GATEWAY_ERROR")
        assert repository.active_turn("alice") is None
        assert repository.get_turn("alice", lease.turn_id).error_code == "MODEL_GATEWAY_ERROR"
    finally:
        service.close()


# -- the legacy wrapper ----------------------------------------------------


def test_run_legacy_refuses_while_a_chat_holds_the_slot(repository):
    """No legacy entry may start a second model call for one account."""
    answer = BlockingAnswer()
    service = _service(repository, answer)
    try:
        submission = _submit(service)
        assert answer.started.wait(2)
        produced = []
        with pytest.raises(TurnSlotBusy):
            service.run_legacy(
                "alice",
                question="Interpret the plan",
                action="adjust_next_plan",
                surface="plan",
                produce=lambda: produced.append(True) or {"answer_markdown": "x"},
            )
        assert produced == [], "the model must not run once admission refuses"
        service.cancel("alice", submission.turn.turn_id)
        service.wait(submission.turn.turn_id, timeout=5)
    finally:
        answer.release.set()
        service.close()


def test_run_legacy_frees_the_slot_when_production_fails(repository):
    service = _service(repository, InstantAnswer())
    try:
        def explode():
            raise RuntimeError("the model refused")

        with pytest.raises(RuntimeError):
            service.run_legacy(
                "alice",
                question="Explain the week",
                action="explain_weekly_report",
                surface="review",
                produce=explode,
            )
        assert repository.active_turn("alice") is None
    finally:
        service.close()


def test_run_legacy_discards_an_answer_the_account_no_longer_owns(repository):
    """A chat deleted while the model ran must not get its answer published."""
    service = _service(repository, InstantAnswer())
    try:
        def produce():
            # The account deletes the quick-action chat mid-flight.
            service.repository.delete_conversation(
                "alice", "system:alice", deleted_at=NOW
            )
            return {"answer_markdown": "Late interpretation", "model": "test-model"}

        with pytest.raises(LegacyAnswerDiscarded):
            service.run_legacy(
                "alice",
                question="Explain the week",
                action="explain_weekly_report",
                surface="review",
                produce=produce,
            )
        assert repository.active_turn("alice") is None
    finally:
        service.close()


def test_legacy_cancel_before_registration_never_starts_production(repository, monkeypatch):
    service = _service(repository, InstantAnswer())
    original = service.begin_legacy

    def accept_then_cancel(*args, **kwargs):
        turn = original(*args, **kwargs)
        repository.request_cancel("alice", turn.turn_id, at=NOW)
        return turn

    monkeypatch.setattr(service, "begin_legacy", accept_then_cancel)
    produced = []
    with pytest.raises(LegacyAnswerDiscarded):
        service.run_legacy("alice", question="Explain", action="explain_today", surface="today",
                           produce=lambda: produced.append(True) or {"answer_markdown": "late"})
    assert produced == []
    assert repository.active_turn("alice") is None
    service.close()


def test_shortcut_then_consecutive_followups_keep_the_saved_reference(repository):
    requests = []

    class Record:
        def run(self, request):
            requests.append(request)
            return CoachTurnAnswer(answer_markdown="Safe explanation", model="synthetic")

    service = _service(repository, Record())
    _conversation(repository)
    try:
        first = service.submit("alice", "c1", idempotency_key="p1", question="Explain saved plan · plan-12345678",
            action="adjust_next_plan", surface="plan", plan_id="plan-12345678")
        service.wait(first.turn.turn_id, timeout=5)
        for key, question in (("p2", "Why?"), ("p3", "More detail")):
            turn = service.submit("alice", "c1", idempotency_key=key, question=question, action="chat", surface="today")
            service.wait(turn.turn.turn_id, timeout=5)
        assert [item.plan_id for item in requests] == ["plan-12345678"] * 3
        assert [item.action for item in requests] == ["adjust_next_plan"] * 3
        assert requests[-1].answer_mode == "detailed"
        # A new goal cannot inherit a saved object's scope through dialogue.
        turn = service.submit("alice", "c1", idempotency_key="p4", question="Pick stocks", action="chat", surface="today")
        service.wait(turn.turn.turn_id, timeout=5)
        assert requests[-1].plan_id is None
        assert requests[-1].action == "chat"
    finally:
        service.close()
