import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backend.application.ports.coach_conversation_repository import (
    CoachConversationConflict,
    CoachConversationDeleted,
)
from backend.domain.coach_conversation import CoachMessage
from backend.infrastructure.repositories.sqlite_coach_conversation_repository import (
    SQLiteCoachConversationRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def database(tmp_path):
    database = SQLiteDatabase(tmp_path / "coach.sqlite")
    run_migrations(database, RECORDS_MIGRATIONS)
    return database


@pytest.fixture
def repository(database):
    return SQLiteCoachConversationRepository(database)


def _ensure_conversation(repository, *, user="alice", conversation="c1", created_at=NOW):
    try:
        return repository.get_conversation(user, conversation)
    except KeyError:
        return repository.create_conversation(
            user, conversation_id=conversation, title="Today", created_at=created_at
        )


def _seed_round(
    repository,
    *,
    user="alice",
    conversation="c1",
    index=0,
    asked_at,
    answered_at=None,
    review_status="approved",
    question="How is today?",
    answer="Steady.",
):
    _ensure_conversation(repository, user=user, conversation=conversation)
    repository.accept_turn(
        user,
        conversation,
        turn_id=f"t-{conversation}-{index}",
        idempotency_key=f"key-{index}",
        request_fingerprint="fingerprint",
        created_at=asked_at,
    )
    repository.append_message(
        user,
        CoachMessage(
            message_id=f"m-{conversation}-{index}-u",
            conversation_id=conversation,
            turn_id=f"t-{conversation}-{index}",
            role="user",
            body=question,
            created_at=asked_at,
        ),
    )
    if answered_at is not None:
        repository.append_message(
            user,
            CoachMessage(
                message_id=f"m-{conversation}-{index}-c",
                conversation_id=conversation,
                turn_id=f"t-{conversation}-{index}",
                role="coach",
                body=answer,
                created_at=answered_at,
                review_status=review_status,
            ),
        )
    # Every seeded round must end, or the next one would be refused by the single
    # execution slot. The publish time is the moment the round actually completed,
    # not the test clock, so an old round is not judged against today's window.
    if answered_at is None:
        status = "cancelled"
    elif review_status == "approved":
        status = "succeeded"
    else:
        status = "failed"
    repository.publish_turn(
        user,
        f"t-{conversation}-{index}",
        status=status,
        updated_at=answered_at or asked_at,
    )


def test_cross_user_access_is_refused(repository):
    repository.create_conversation(
        "alice", conversation_id="c1", title="Today", created_at=NOW
    )
    _seed_round(repository, asked_at=NOW, answered_at=NOW)

    with pytest.raises(KeyError):
        repository.get_conversation("bob", "c1")
    with pytest.raises(KeyError):
        repository.rename_conversation("bob", "c1", title="stolen", updated_at=NOW)
    with pytest.raises(KeyError):
        repository.delete_conversation("bob", "c1", deleted_at=NOW)
    with pytest.raises(KeyError):
        repository.accept_turn(
            "bob",
            "c1",
            turn_id="t-bob",
            idempotency_key="bob-key",
            request_fingerprint="fingerprint",
            created_at=NOW,
        )
    with pytest.raises(KeyError):
        repository.list_messages("bob", "c1", now=NOW)
    assert repository.list_conversations("bob") == ()
    assert len(repository.list_conversations("alice")) == 1


def test_the_schema_refuses_a_message_from_another_account(database, repository):
    """Ownership is a database constraint, not only a Python check."""
    repository.create_conversation(
        "alice", conversation_id="c1", title="Today", created_at=NOW
    )
    _seed_round(repository, asked_at=NOW, answered_at=NOW)

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO coach_messages(
                    message_id, turn_id, conversation_id, user_id,
                    role, body, review_status, created_at
                ) VALUES ('forged', 't-c1-0', 'c1', 'bob', 'user', 'hi',
                          'approved', '2026-10-18T12:00:00.000000Z')
                """
            )


def test_a_late_publish_after_deletion_is_refused(repository):
    repository.create_conversation(
        "alice", conversation_id="c1", title="Today", created_at=NOW
    )
    _seed_round(repository, asked_at=NOW)

    assert repository.delete_conversation("alice", "c1", deleted_at=NOW) is True
    assert repository.delete_conversation("alice", "c1", deleted_at=NOW) is False

    assert (
        repository.publish_turn("alice", "t-c1-0", status="succeeded", updated_at=NOW)
        is False
    )
    with pytest.raises(CoachConversationDeleted):
        repository.append_message(
            "alice",
            CoachMessage(
                message_id="late",
                conversation_id="c1",
                turn_id="t-c1-0",
                role="coach",
                body="Late answer",
                created_at=NOW,
            ),
        )
    # A deleted chat is a 404, not an empty transcript.
    with pytest.raises(KeyError):
        repository.list_messages("alice", "c1", now=NOW)


def test_deletion_is_a_lifecycle_change_not_a_cascade(repository, database):
    repository.create_conversation(
        "alice", conversation_id="c1", title="Today", created_at=NOW
    )
    _seed_round(repository, asked_at=NOW, answered_at=NOW)

    with database.connection() as connection:
        before = connection.execute("SELECT COUNT(*) FROM coach_messages").fetchone()[0]

    repository.delete_conversation("alice", "c1", deleted_at=NOW)

    with database.connection() as connection:
        after = connection.execute("SELECT COUNT(*) FROM coach_messages").fetchone()[0]
        row = connection.execute(
            "SELECT status FROM coach_conversations WHERE conversation_id='c1'"
        ).fetchone()
    # Referenced business objects and the audit trail survive the chat deletion.
    assert after == before
    assert row["status"] == "deleted"


def test_the_ninety_day_window_applies_before_cleanup(repository):
    _seed_round(
        repository,
        index=0,
        asked_at=NOW - timedelta(days=91),
        answered_at=NOW - timedelta(days=91),
    )
    _seed_round(
        repository, index=1, asked_at=NOW - timedelta(days=1), answered_at=NOW
    )

    messages = repository.list_messages("alice", "c1", now=NOW)
    assert [message.body for message in messages] == ["How is today?", "Steady."]

    # Nothing has been swept yet: the old rows are hidden, not gone.
    assert repository.purge_expired(NOW) == 2
    assert repository.purge_expired(NOW) == 0


def test_a_reply_expires_with_its_question(repository):
    """The answer is inside the window; the question it answered is not."""
    _seed_round(
        repository,
        index=0,
        asked_at=NOW - timedelta(days=91),
        answered_at=NOW - timedelta(days=89),
    )

    assert repository.list_messages("alice", "c1", now=NOW) == ()
    assert repository.purge_expired(NOW) == 2


def test_the_window_boundary_is_strict(repository):
    _seed_round(
        repository,
        index=0,
        asked_at=NOW - timedelta(days=90),
        answered_at=NOW - timedelta(days=90),
    )
    _seed_round(
        repository,
        index=1,
        asked_at=NOW - timedelta(days=90) + timedelta(microseconds=1),
        answered_at=NOW - timedelta(days=90) + timedelta(microseconds=1),
    )

    messages = repository.list_messages("alice", "c1", now=NOW)
    assert len(messages) == 2


def test_blank_titles_are_stored_as_null_and_rename_can_clear_them(repository):
    conversation = repository.create_conversation(
        "alice", conversation_id="c1", title="   ", created_at=NOW
    )
    assert conversation.title is None

    renamed = repository.rename_conversation(
        "alice", "c1", title="  今天的   蛋白质 ", updated_at=NOW
    )
    assert renamed.title == "今天的 蛋白质"

    cleared = repository.rename_conversation(
        "alice", "c1", title="  ", updated_at=NOW
    )
    assert cleared.title is None

    with pytest.raises(sqlite3.IntegrityError):
        with repository.database.transaction() as connection:
            connection.execute(
                "UPDATE coach_conversations SET title='' WHERE conversation_id='c1'"
            )


def test_accepting_the_same_turn_twice_never_creates_a_second_run(repository):
    repository.create_conversation(
        "alice", conversation_id="c1", title="Today", created_at=NOW
    )
    first = repository.accept_turn(
        "alice",
        "c1",
        turn_id="t1",
        idempotency_key="key",
        request_fingerprint="fp",
        created_at=NOW,
    )
    second = repository.accept_turn(
        "alice",
        "c1",
        turn_id="t-other",
        idempotency_key="key",
        request_fingerprint="fp",
        created_at=NOW,
    )
    assert first.turn_id == second.turn_id == "t1"
    assert repository.get_turn("alice", "t1").status == "queued"

    with pytest.raises(CoachConversationConflict):
        repository.accept_turn(
            "alice",
            "c1",
            turn_id="t2",
            idempotency_key="key",
            request_fingerprint="different",
            created_at=NOW,
        )


def test_publishing_a_terminal_state_is_idempotent(repository):
    repository.create_conversation(
        "alice", conversation_id="c1", title="Today", created_at=NOW
    )
    repository.accept_turn(
        "alice",
        "c1",
        turn_id="t1",
        idempotency_key="key",
        request_fingerprint="fp",
        created_at=NOW,
    )
    # A succeeded publish requires a reviewed answer, so store one first.
    repository.append_message(
        "alice",
        CoachMessage(
            message_id="m1",
            conversation_id="c1",
            turn_id="t1",
            role="coach",
            body="Steady.",
            created_at=NOW,
            review_status="approved",
        ),
    )

    assert repository.publish_turn("alice", "t1", status="succeeded", updated_at=NOW)
    assert repository.publish_turn("alice", "t1", status="succeeded", updated_at=NOW)
    assert not repository.publish_turn("alice", "t1", status="failed", updated_at=NOW)
    assert repository.get_turn("alice", "t1").status == "succeeded"

    with pytest.raises(ValueError):
        repository.publish_turn("alice", "t1", status="running", updated_at=NOW)


def test_listing_hides_deleted_conversations_and_is_paginated(repository):
    for index in range(3):
        repository.create_conversation(
            "alice",
            conversation_id=f"c{index}",
            title=f"Chat {index}",
            created_at=NOW + timedelta(minutes=index),
        )
    repository.delete_conversation("alice", "c1", deleted_at=NOW)

    listed = repository.list_conversations("alice")
    assert [conversation.conversation_id for conversation in listed] == ["c2", "c0"]
    assert [conversation.conversation_id for conversation in repository.list_conversations("alice", limit=1)] == ["c2"]
    older = repository.list_conversations("alice", before=NOW + timedelta(minutes=2))
    assert [conversation.conversation_id for conversation in older] == ["c0"]


def test_export_excludes_expired_text_and_deleted_chats(repository):
    import json

    _seed_round(
        repository,
        conversation="c-old",
        index=0,
        asked_at=NOW - timedelta(days=120),
        answered_at=NOW - timedelta(days=120),
        question="expired question",
        answer="expired answer",
    )
    _seed_round(
        repository,
        conversation="c-fresh",
        index=1,
        asked_at=NOW - timedelta(days=1),
        answered_at=NOW,
        question="fresh question",
        answer="fresh answer",
    )
    _seed_round(
        repository,
        conversation="c-deleted",
        index=2,
        asked_at=NOW,
        answered_at=NOW,
        question="deleted question",
        answer="deleted answer",
    )
    repository.delete_conversation("alice", "c-deleted", deleted_at=NOW)

    payload = json.loads(
        repository.export_conversations("alice", max_bytes=1_000_000, now=NOW)
    )
    exported = {
        conversation["conversation_id"]: [
            message["body"] for message in conversation["messages"]
        ]
        for conversation in payload["conversations"]
    }
    assert exported == {"c-fresh": ["fresh question", "fresh answer"]}


def test_export_refuses_to_exceed_its_budget(repository):
    _seed_round(
        repository,
        index=0,
        asked_at=NOW - timedelta(days=1),
        answered_at=NOW,
        question="q" * 500,
        answer="a" * 500,
    )
    with pytest.raises(ValueError):
        repository.export_conversations("alice", max_bytes=64, now=NOW)


def test_deleting_an_account_removes_only_its_own_chats(repository):
    for owner in ("alice", "bob"):
        repository.create_conversation(
            owner, conversation_id=f"{owner}-c1", title="Today", created_at=NOW
        )
        _seed_round(
            repository,
            user=owner,
            conversation=f"{owner}-c1",
            asked_at=NOW - timedelta(seconds=1),
            answered_at=NOW,
        )

    repository.delete_user_data("alice")

    with pytest.raises(KeyError):
        repository.get_conversation("alice", "alice-c1")
    assert repository.get_conversation("bob", "bob-c1").user_id == "bob"
    assert len(repository.list_messages("bob", "bob-c1", now=NOW)) == 2
