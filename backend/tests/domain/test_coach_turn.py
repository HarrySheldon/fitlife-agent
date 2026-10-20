"""Turn lifecycle: one execution slot per account, cancel intent, terminal receipts.

The rules here are pure. Storage enforces them inside a transaction; this module
only decides what is legal, so a reviewer can check the policy without reading SQL.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.domain.coach_turn import (
    CANCELLATION_NOTICE,
    TurnNotCancellable,
    TurnSlotBusy,
    TurnState,
    TurnVersionConflict,
    holds_slot,
    is_stopping,
    require_slot_free,
    transition,
)

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def _turn(
    status="queued",
    *,
    turn_id="t-1",
    user="alice",
    conversation="c-1",
    version=1,
    cancel_requested_at=None,
    age_seconds=0,
):
    return TurnState(
        turn_id=turn_id,
        user_id=user,
        conversation_id=conversation,
        status=status,
        version=version,
        cancel_requested_at=cancel_requested_at,
        created_at=NOW - timedelta(seconds=age_seconds),
        finished_at=None,
    )


# -- the single slot -------------------------------------------------------


@pytest.mark.parametrize("status", ["queued", "running"])
def test_queued_and_running_hold_the_execution_slot(status):
    assert holds_slot(_turn(status)) is True


@pytest.mark.parametrize(
    "status",
    ["awaiting_user", "succeeded", "failed", "cancelled", "interrupted", "expired"],
)
def test_waiting_and_terminal_states_release_the_execution_slot(status):
    """A user who must answer a question is not occupying a model."""
    assert holds_slot(_turn(status)) is False


def test_a_second_turn_is_refused_while_the_slot_is_held():
    active = _turn("running")
    with pytest.raises(TurnSlotBusy) as raised:
        require_slot_free([active])
    assert raised.value.active_turn_id == "t-1"
    assert raised.value.code == "COACH_TURN_BUSY"


def test_a_stopping_turn_still_holds_the_slot():
    """Cancellation is a request, not a release: the transport has not closed yet."""
    stopping = _turn("running", cancel_requested_at=NOW)
    assert is_stopping(stopping) is True
    assert holds_slot(stopping) is True
    with pytest.raises(TurnSlotBusy):
        require_slot_free([stopping])


def test_a_free_slot_admits_exactly_one_turn():
    require_slot_free([_turn("succeeded"), _turn("awaiting_user", turn_id="t-2")])


# -- transitions -----------------------------------------------------------


def test_running_can_reach_every_legal_successor():
    for target in ("awaiting_user", "succeeded", "failed", "cancelled", "interrupted", "expired"):
        assert transition(_turn("running"), target, at=NOW).status == target


def test_a_terminal_turn_only_repeats_itself():
    finished = _turn("succeeded")
    assert transition(finished, "succeeded", at=NOW).status == "succeeded"
    with pytest.raises(TurnVersionConflict):
        transition(finished, "failed", at=NOW)


def test_transition_bumps_the_version_and_stamps_the_finish():
    moved = transition(_turn("running", version=3), "succeeded", at=NOW)
    assert moved.version == 4
    assert moved.finished_at == NOW


def test_a_stale_expected_version_is_rejected():
    with pytest.raises(TurnVersionConflict):
        transition(_turn("running", version=3), "succeeded", at=NOW, expected_version=2)


def test_cancel_is_refused_once_the_turn_is_terminal():
    with pytest.raises(TurnNotCancellable):
        transition(_turn("succeeded"), "cancelled", at=NOW)


def test_cancel_from_a_waiting_turn_is_legal_and_needs_no_transport():
    cancelled = transition(_turn("awaiting_user"), "cancelled", at=NOW)
    assert cancelled.status == "cancelled"
    assert holds_slot(cancelled) is False


def test_cancelling_an_already_stopping_turn_is_a_no_op_not_a_second_close():
    stopping = _turn("running", cancel_requested_at=NOW - timedelta(seconds=5))
    assert is_stopping(stopping) is True
    again = transition(stopping, "running", at=NOW)
    assert again.cancel_requested_at == stopping.cancel_requested_at


def test_unknown_statuses_are_refused_rather_than_guessed():
    with pytest.raises(ValueError):
        transition(_turn("running"), "finished", at=NOW)


def test_a_turn_requires_an_owner_and_a_conversation():
    with pytest.raises(ValueError):
        _turn(user=" ")
    with pytest.raises(ValueError):
        _turn(conversation="")


def test_the_cancellation_notice_states_the_irreversible_cost_in_both_languages():
    assert set(CANCELLATION_NOTICE) == {"zh-CN", "en-US"}
    assert "费用" in CANCELLATION_NOTICE["zh-CN"]
    assert "charge" in CANCELLATION_NOTICE["en-US"]
