from datetime import datetime, timedelta, timezone

import pytest

from backend.domain.coach_conversation import (
    MAX_CONTEXT_ROUNDS,
    CoachConversationError,
    CoachMessage,
    derive_conversation_title,
    message_visible,
    project_context,
    turn_is_terminal,
    visible_messages,
)

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def _message(
    index,
    *,
    role="user",
    body="hello",
    conversation_id="conv-1",
    age_days=0,
    seconds=0,
    review_status="approved",
    turn_id=None,
):
    return CoachMessage(
        message_id=f"m-{index}",
        conversation_id=conversation_id,
        turn_id=turn_id or f"t-{index}",
        role=role,
        body=body,
        created_at=NOW - timedelta(days=age_days, seconds=seconds),
        review_status=review_status,
    )


def _round(index, *, conversation_id="conv-1", body="hello", age_days=0):
    return (
        _message(
            index * 2,
            conversation_id=conversation_id,
            body=body,
            age_days=age_days,
            turn_id=f"t-{conversation_id}-{index}",
        ),
        _message(
            index * 2 + 1,
            role="coach",
            conversation_id=conversation_id,
            body=body,
            age_days=age_days,
            turn_id=f"t-{conversation_id}-{index}",
        ),
    )


def test_exact_ninety_days_is_expired():
    now = datetime(2026, 10, 18, tzinfo=timezone.utc)
    assert not message_visible(now - timedelta(days=90), now)
    assert message_visible(now - timedelta(days=90) + timedelta(microseconds=1), now)


def test_naive_timestamps_are_rejected():
    with pytest.raises(ValueError):
        message_visible(datetime(2026, 10, 18), NOW)
    with pytest.raises(ValueError):
        message_visible(NOW, datetime(2026, 10, 18))


def test_a_future_message_is_not_visible():
    assert not message_visible(NOW + timedelta(seconds=1), NOW)
    assert message_visible(NOW, NOW)


def test_visible_messages_drop_expired_entries():
    fresh = _message(1, age_days=1)
    edge = _message(2, age_days=90)
    assert visible_messages((fresh, edge), conversation_id="conv-1", now=NOW) == (fresh,)


def test_visible_messages_never_return_another_conversation():
    mine = _message(1)
    other = _message(2, conversation_id="conv-2")
    assert visible_messages((mine, other), conversation_id="conv-1", now=NOW) == (mine,)


def test_blank_message_text_cannot_be_stored():
    with pytest.raises(CoachConversationError):
        _message(1, body="   ")


def test_unknown_role_and_review_status_are_rejected():
    with pytest.raises(CoachConversationError):
        _message(1, role="system")
    with pytest.raises(CoachConversationError):
        _message(1, review_status="published")


def test_blank_title_is_cleared():
    assert derive_conversation_title("   \n\t ") is None
    assert derive_conversation_title("") is None


def test_title_collapses_whitespace_and_is_bounded():
    assert derive_conversation_title("  今天  的   蛋白质 ") == "今天 的 蛋白质"
    title = derive_conversation_title("长" * 100)
    assert title is not None
    assert len(title) == 40


def test_terminal_statuses_are_the_ones_that_release_the_slot():
    for status in ("succeeded", "failed", "cancelled", "interrupted", "expired"):
        assert turn_is_terminal(status) is True
    for status in ("queued", "running", "awaiting_user"):
        assert turn_is_terminal(status) is False
    with pytest.raises(CoachConversationError):
        turn_is_terminal("done")


def test_context_projection_keeps_only_complete_rounds_of_the_same_conversation():
    mine = _round(0, body="today")
    theirs = _round(0, conversation_id="conv-2", body="other")
    projection = project_context(
        (*theirs, *mine), conversation_id="conv-1", now=NOW
    )
    assert projection.rounds == 1
    assert [message.body for message in projection.messages] == ["today", "today"]
    assert [message.role for message in projection.messages] == ["user", "coach"]


def test_context_projection_skips_unapproved_coach_text():
    user, coach = _round(0)
    pending = CoachMessage(
        message_id="m-pending",
        conversation_id="conv-1",
        turn_id=user.turn_id,
        role="coach",
        body="unreviewed draft",
        created_at=NOW,
        review_status="pending",
    )
    projection = project_context((user, pending), conversation_id="conv-1", now=NOW)
    assert projection.messages == ()
    assert projection.rounds == 0

    approved = project_context((user, coach), conversation_id="conv-1", now=NOW)
    assert len(approved.messages) == 2


def test_context_projection_drops_expired_rounds():
    stale = _round(0, age_days=90)
    fresh = _round(1, age_days=1)
    projection = project_context((*stale, *fresh), conversation_id="conv-1", now=NOW)
    assert projection.rounds == 1
    assert all(message.body == "hello" for message in projection.messages)


def test_context_projection_keeps_the_most_recent_six_rounds():
    rounds = []
    for index in range(8):
        rounds.extend(_round(index, body=f"round-{index}", age_days=8 - index))
    projection = project_context(tuple(rounds), conversation_id="conv-1", now=NOW)
    assert projection.rounds == MAX_CONTEXT_ROUNDS
    assert [message.body for message in projection.messages[::2]] == [
        "round-2",
        "round-3",
        "round-4",
        "round-5",
        "round-6",
        "round-7",
    ]


def test_context_projection_respects_the_character_budget():
    rounds = []
    for index in range(3):
        rounds.extend(_round(index, body="abcde", age_days=3 - index))
    projection = project_context(
        tuple(rounds), conversation_id="conv-1", now=NOW, character_budget=12
    )
    assert projection.rounds == 1
    assert projection.characters == 10


def test_context_projection_requires_a_budget_and_conversation():
    with pytest.raises(CoachConversationError):
        project_context((), conversation_id="", now=NOW)
    with pytest.raises(CoachConversationError):
        project_context((), conversation_id="conv-1", now=NOW, character_budget=0)
