"""Storage-level turn lifecycle: one slot, cancel intent, guarded publication.

These tests exercise the invariants that must survive a concurrent caller: the
slot is taken atomically, a stop never frees the slot, and a late answer cannot
overwrite a cancel, a deletion or an unreviewed draft.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.application.ports.coach_conversation_repository import (
    CoachConversationConflict,
)
from backend.domain.coach_conversation import CoachMessage
from backend.domain.coach_turn import TurnNotCancellable, TurnSlotBusy
from backend.infrastructure.repositories.sqlite_coach_conversation_repository import (
    SQLiteCoachConversationRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


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


def _accept(repository, *, user="alice", conversation="c1", turn="t1", key="k1"):
    _conversation(repository, user=user, conversation=conversation)
    return repository.accept_turn(
        user,
        conversation,
        turn_id=turn,
        idempotency_key=key,
        request_fingerprint="fp",
        created_at=NOW,
    )


def _answer(repository, *, user="alice", conversation="c1", turn="t1", body="Steady.",
            review_status="approved", at=None):
    return repository.append_message(
        user,
        CoachMessage(
            message_id=f"{turn}-coach",
            conversation_id=conversation,
            turn_id=turn,
            role="coach",
            body=body,
            created_at=at or NOW,
            review_status=review_status,
        ),
    )


# -- the single slot -------------------------------------------------------


def test_a_second_key_is_refused_while_the_first_turn_runs(repository):
    _accept(repository)

    with pytest.raises(TurnSlotBusy) as raised:
        repository.accept_turn(
            "alice", "c1", turn_id="t2", idempotency_key="k2",
            request_fingerprint="fp", created_at=NOW,
        )
    assert raised.value.active_turn_id == "t1"


def test_repeating_the_same_key_returns_the_same_turn_even_while_it_runs(repository):
    first = _accept(repository)
    again = repository.accept_turn(
        "alice", "c1", turn_id="t2", idempotency_key="k1",
        request_fingerprint="fp", created_at=NOW,
    )
    assert again.turn_id == first.turn_id == "t1"


def test_the_same_key_with_different_content_conflicts(repository):
    _accept(repository)
    with pytest.raises(CoachConversationConflict):
        repository.accept_turn(
            "alice", "c1", turn_id="t1", idempotency_key="k1",
            request_fingerprint="other", created_at=NOW,
        )


def test_another_account_has_its_own_slot(repository):
    _accept(repository, user="alice", conversation="c1", turn="t1", key="k1")
    other = _accept(repository, user="bob", conversation="c2", turn="t2", key="k2")
    assert other.user_id == "bob"
    assert repository.active_turn("alice").turn_id == "t1"
    assert repository.active_turn("bob").turn_id == "t2"


def test_a_terminal_turn_frees_the_slot(repository):
    _accept(repository)
    _answer(repository)
    assert repository.publish_turn("alice", "t1", status="succeeded", updated_at=NOW)
    assert repository.active_turn("alice") is None

    admitted = repository.accept_turn(
        "alice", "c1", turn_id="t2", idempotency_key="k2",
        request_fingerprint="fp", created_at=NOW,
    )
    assert admitted.turn_id == "t2"


def test_waiting_for_the_user_frees_the_slot_without_finishing_the_turn(repository):
    _accept(repository)
    repository.claim_turn("alice", "t1", lease_id="worker-1", started_at=NOW)

    waiting = repository.release_slot("alice", "t1", at=NOW)

    assert waiting.status == "awaiting_user"
    assert waiting.slot_released_at == NOW
    assert repository.active_turn("alice") is None
    repository.accept_turn(
        "alice", "c1", turn_id="t2", idempotency_key="k2",
        request_fingerprint="fp", created_at=NOW,
    )


# -- cancellation ----------------------------------------------------------


def test_cancel_records_intent_without_releasing_the_slot(repository):
    _accept(repository)
    repository.claim_turn("alice", "t1", lease_id="worker-1", started_at=NOW)

    stopping = repository.request_cancel("alice", "t1", at=NOW)

    assert stopping.status == "running"
    assert stopping.cancel_requested_at == NOW
    # The transport has not closed yet, so a second turn is still refused.
    assert repository.active_turn("alice").turn_id == "t1"
    with pytest.raises(TurnSlotBusy):
        repository.accept_turn(
            "alice", "c1", turn_id="t2", idempotency_key="k2",
            request_fingerprint="fp", created_at=NOW,
        )


def test_cancelling_twice_does_not_open_a_second_close(repository):
    _accept(repository)
    repository.claim_turn("alice", "t1", lease_id="worker-1", started_at=NOW)
    first = repository.request_cancel("alice", "t1", at=NOW)
    second = repository.request_cancel("alice", "t1", at=NOW + timedelta(seconds=3))

    assert second.cancel_requested_at == first.cancel_requested_at
    assert second.version == first.version


def test_a_cancelled_turn_cannot_be_published_as_succeeded(repository):
    _accept(repository)
    repository.claim_turn("alice", "t1", lease_id="worker-1", started_at=NOW)
    repository.request_cancel("alice", "t1", at=NOW)
    _answer(repository)

    assert not repository.publish_turn("alice", "t1", status="succeeded", updated_at=NOW)
    assert repository.get_turn("alice", "t1").status == "running"

    assert repository.publish_turn("alice", "t1", status="cancelled", updated_at=NOW)
    assert repository.get_turn("alice", "t1").status == "cancelled"


def test_cancelling_a_finished_turn_is_refused(repository):
    _accept(repository)
    _answer(repository)
    repository.publish_turn("alice", "t1", status="succeeded", updated_at=NOW)

    with pytest.raises(TurnNotCancellable):
        repository.request_cancel("alice", "t1", at=NOW)


# -- guarded publication ---------------------------------------------------


def test_an_unreviewed_answer_cannot_be_published(repository):
    _accept(repository)
    _answer(repository, review_status="pending")

    assert not repository.publish_turn("alice", "t1", status="succeeded", updated_at=NOW)
    assert repository.get_turn("alice", "t1").status == "queued"


def test_a_rejected_answer_cannot_be_published(repository):
    _accept(repository)
    _answer(repository, review_status="rejected")
    assert not repository.publish_turn("alice", "t1", status="succeeded", updated_at=NOW)


def test_a_stale_version_is_not_published(repository):
    _accept(repository)
    _answer(repository)
    current = repository.get_turn("alice", "t1")

    assert not repository.publish_turn(
        "alice", "t1", status="succeeded", updated_at=NOW,
        expected_version=current.version + 5,
    )


def test_a_turn_older_than_the_retention_window_cannot_succeed(repository):
    _accept(repository)
    _answer(repository)
    later = NOW + timedelta(days=90)

    assert not repository.publish_turn("alice", "t1", status="succeeded", updated_at=later)
    assert repository.publish_turn("alice", "t1", status="expired", updated_at=later)


def test_a_deleted_conversation_cannot_receive_a_terminal_state(repository):
    _accept(repository)
    _answer(repository)
    repository.delete_conversation("alice", "c1", deleted_at=NOW)

    assert not repository.publish_turn("alice", "t1", status="succeeded", updated_at=NOW)


def test_a_receipt_is_stored_once_and_replayed_on_retry(repository):
    _accept(repository)
    _answer(repository)
    assert repository.publish_turn(
        "alice", "t1", status="succeeded", updated_at=NOW, receipt_json='{"v":1}'
    )
    assert repository.publish_turn(
        "alice", "t1", status="succeeded", updated_at=NOW, receipt_json='{"v":2}'
    )
    assert repository.get_turn("alice", "t1").receipt_json == '{"v":1}'


def test_claiming_moves_queued_to_running_and_records_the_lease(repository):
    _accept(repository)
    claimed = repository.claim_turn(
        "alice", "t1", lease_id="worker-1", started_at=NOW
    )
    assert claimed.status == "running"
    assert claimed.lease_id == "worker-1"
    assert claimed.started_at == NOW


# -- restart recovery ------------------------------------------------------


def test_startup_interrupts_turns_of_other_processes_only(repository):
    _accept(repository, conversation="c1", turn="t1", key="k1")
    repository.claim_turn("alice", "t1", lease_id="worker-old", started_at=NOW)
    _accept(repository, user="bob", conversation="c2", turn="t2", key="k2")
    repository.claim_turn("bob", "t2", lease_id="worker-live", started_at=NOW)

    changed = repository.interrupt_stale_turns(("worker-live",), at=NOW)

    assert changed == 1
    assert repository.get_turn("alice", "t1").status == "interrupted"
    assert repository.get_turn("bob", "t2").status == "running"


def test_an_interrupted_turn_frees_its_slot_and_is_never_resent(repository):
    _accept(repository)
    repository.claim_turn("alice", "t1", lease_id="worker-old", started_at=NOW)
    repository.interrupt_stale_turns((), at=NOW)

    interrupted = repository.get_turn("alice", "t1")
    assert interrupted.status == "interrupted"
    assert repository.active_turn("alice") is None
    # Publishing a late result is refused: the turn already ended.
    _answer(repository)
    assert not repository.publish_turn("alice", "t1", status="succeeded", updated_at=NOW)


def test_interrupting_twice_changes_nothing_further(repository):
    _accept(repository)
    repository.claim_turn("alice", "t1", lease_id="worker-old", started_at=NOW)
    assert repository.interrupt_stale_turns((), at=NOW) == 1
    assert repository.interrupt_stale_turns((), at=NOW) == 0
