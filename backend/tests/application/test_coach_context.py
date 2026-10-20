import inspect
from datetime import datetime, timedelta, timezone

import pytest

from backend.application.ports.coach_conversation_repository import (
    CoachConversationRepository,
)
from backend.application.use_cases.coach_conversations import CoachConversations
from backend.domain.coach_conversation import CoachMessage
from backend.infrastructure.repositories.sqlite_coach_conversation_repository import (
    SQLiteCoachConversationRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)

MAINTENANCE_METHODS = {"purge_expired", "interrupt_stale_turns"}
"""Sweeps that legitimately cross accounts: one returns a count, the other a
restart-recovery count. Neither returns message text, so neither can leak one
account's conversation to another."""


def _public_methods():
    for name, member in vars(CoachConversationRepository).items():
        if name.startswith("_") or name in MAINTENANCE_METHODS:
            continue
        if callable(member):
            yield name, member


def test_every_owner_scoped_method_takes_user_id_first():
    """The owner is a positional argument, so no request body can supply or override it."""
    methods = dict(_public_methods())
    assert methods, "the repository protocol exposes no methods"
    for name, method in methods.items():
        parameters = [
            parameter
            for parameter in inspect.signature(method).parameters.values()
            if parameter.name != "self"
        ]
        assert parameters, f"{name} takes no arguments"
        assert parameters[0].name == "user_id", f"{name} must take user_id first"
        assert parameters[0].default is inspect.Parameter.empty, (
            f"{name} must not default user_id"
        )


def test_message_writes_cannot_claim_an_author_or_timestamp_from_the_client():
    """The port stores a domain message, so role and created_at are already server-built."""
    append = inspect.signature(CoachConversationRepository.append_message)
    assert list(append.parameters) == ["self", "user_id", "message"]
    assert append.parameters["message"].annotation == "CoachMessage"

    list_messages = inspect.signature(CoachConversationRepository.list_messages)
    assert "now" in list_messages.parameters, (
        "the read path must receive the clock so the 90-day window is not implicit"
    )


def test_purge_is_the_only_sweep_without_an_owner():
    """A maintenance sweep may cross accounts, but it only returns a count."""
    signature = inspect.signature(CoachConversationRepository.purge_expired)
    assert "user_id" not in signature.parameters
    assert signature.return_annotation == "int"


@pytest.fixture
def coach(tmp_path):
    database = SQLiteDatabase(tmp_path / "coach.sqlite")
    run_migrations(database, RECORDS_MIGRATIONS)
    return CoachConversations(
        SQLiteCoachConversationRepository(database),
        clock=lambda: NOW,
        id_factory=lambda: "conversation-1",
    )


def _seed_round(coach, *, user="alice", conversation, turn, question, answer, age_days=0):
    moment = NOW - timedelta(days=age_days)
    coach.repository.accept_turn(
        user,
        conversation,
        turn_id=turn,
        idempotency_key=f"key-{turn}",
        request_fingerprint="fingerprint",
        created_at=moment,
    )
    for role, body, offset in (
        ("user", question, -1),
        ("coach", answer, 0),
    ):
        coach.repository.append_message(
            user,
            CoachMessage(
                message_id=f"{turn}-{role}",
                conversation_id=conversation,
                turn_id=turn,
                role=role,
                body=body,
                created_at=moment + timedelta(seconds=offset),
            ),
        )
    # Finish the turn: one account may hold the execution slot for one turn at a
    # time, so a seeded history that never ends would block the next seed.
    coach.repository.publish_turn(
        user, turn, status="succeeded", updated_at=moment
    )


def test_creation_uses_server_generated_identity_and_timestamp(coach):
    conversation = coach.create("alice", title="  今天  ")
    assert conversation.conversation_id == "conversation-1"
    assert conversation.created_at == NOW
    assert conversation.title == "今天"
    assert conversation.user_id == "alice"


def test_context_excludes_the_in_flight_turn(coach):
    coach.create("alice")
    _seed_round(coach, conversation="conversation-1", turn="t1", question="q1", answer="a1")
    _seed_round(coach, conversation="conversation-1", turn="t2", question="q2", answer="a2")

    projection = coach.context(
        "alice", conversation_id="conversation-1", turn_id="t2"
    )
    assert [message.body for message in projection.messages] == ["q1", "a1"]


def test_context_never_reads_another_conversation(coach):
    coach.create("alice")
    coach.repository.create_conversation(
        "alice", conversation_id="conversation-2", title=None, created_at=NOW
    )
    _seed_round(coach, conversation="conversation-1", turn="t1", question="mine", answer="ok")
    _seed_round(
        coach, conversation="conversation-2", turn="t9", question="theirs", answer="nope"
    )

    projection = coach.context("alice", conversation_id="conversation-1", turn_id="t3")
    assert [message.body for message in projection.messages] == ["mine", "ok"]


def test_context_stops_when_the_remaining_budget_is_zero(coach):
    coach.create("alice")
    _seed_round(coach, conversation="conversation-1", turn="t1", question="q", answer="a")

    projection = coach.context(
        "alice", conversation_id="conversation-1", turn_id="t2", character_budget=0
    )
    assert projection.messages == ()
    assert projection.rounds == 0


def test_context_is_bounded_by_the_remaining_budget(coach):
    coach.create("alice")
    for index in range(3):
        _seed_round(
            coach,
            conversation="conversation-1",
            turn=f"t{index}",
            question="abcde",
            answer="vwxyz",
            age_days=3 - index,
        )

    projection = coach.context(
        "alice", conversation_id="conversation-1", turn_id="t9", character_budget=12
    )
    assert projection.rounds == 1
    assert projection.characters == 10


def test_context_requires_an_owned_conversation(coach):
    coach.create("alice")
    with pytest.raises(KeyError):
        coach.context("bob", conversation_id="conversation-1", turn_id="t1")


def test_deletion_is_owner_scoped(coach):
    coach.create("alice")
    with pytest.raises(KeyError):
        coach.delete("bob", "conversation-1")
    assert coach.delete("alice", "conversation-1") is True
    assert coach.list("alice") == ()


def test_an_owner_must_be_supplied_explicitly(coach):
    with pytest.raises(ValueError):
        coach.create("  ")
    with pytest.raises(ValueError):
        coach.list("")
