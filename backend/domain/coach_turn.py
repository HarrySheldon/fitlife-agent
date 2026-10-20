"""Turn lifecycle rules: one execution slot per account, cancel intent, receipts.

Two ideas carry this module.

*Execution slot.* An account may run at most one turn at a time. ``queued`` and
``running`` hold the slot. ``awaiting_user`` does not: a turn waiting for the user
to answer a clarification is not using a model, so it must not block the next
question. Terminal states never hold it.

*Cancellation is a request, not a release.* A cancel sets ``cancel_requested_at``
and leaves the turn ``running`` until the transport actually closes. That is the
``stopping`` state, and it still holds the slot — otherwise a second turn could
start while the first model call is still burning tokens. Only a terminal publish
releases the slot.

Nothing here reads a database. Storage applies these decisions inside one
transaction; this module only decides what is legal.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

TurnStatus = Literal[
    "queued",
    "running",
    "awaiting_user",
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
    "expired",
]

SLOT_HOLDING_STATUSES: frozenset[str] = frozenset({"queued", "running"})
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"succeeded", "failed", "cancelled", "interrupted", "expired"}
)

_ALLOWED: dict[str, frozenset[str]] = {
    # ``queued`` may finish without ever being claimed: a turn that fails before
    # an executor takes ownership still has to reach a terminal state, and a
    # synthetic claim would only invent a lease that never existed.
    "queued": frozenset(
        {"running", "succeeded", "failed", "cancelled", "interrupted", "expired"}
    ),
    "running": frozenset(
        {"awaiting_user", "succeeded", "failed", "cancelled", "interrupted", "expired"}
    ),
    "awaiting_user": frozenset(
        {"running", "cancelled", "failed", "interrupted", "expired"}
    ),
}

CANCELLATION_NOTICE: dict[str, str] = {
    "zh-CN": "模型调用可能已经产生费用，取消不会退还这部分费用。",
    "en-US": "The model call may already have incurred a charge; cancelling does not refund it.",
}
"""Stated to the user, not buried in a log: cancelling stops work, not billing."""


class CoachTurnError(ValueError):
    pass


class TurnSlotBusy(CoachTurnError):
    """Another turn of the same account holds the single execution slot."""

    code = "COACH_TURN_BUSY"

    def __init__(self, active_turn_id: str) -> None:
        super().__init__("another turn is already running")
        self.active_turn_id = active_turn_id


class TurnVersionConflict(CoachTurnError):
    """The turn moved on, or a terminal state cannot be replaced by another one."""

    code = "TURN_VERSION_CONFLICT"


class TurnNotCancellable(CoachTurnError):
    code = "TURN_NOT_CANCELLABLE"


def _require_identity(value: str, *, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")


def _require_aware(value: datetime, *, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} requires an aware timestamp")


@dataclass(frozen=True)
class TurnState:
    turn_id: str
    user_id: str
    conversation_id: str
    status: TurnStatus
    version: int
    created_at: datetime
    cancel_requested_at: datetime | None = None
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_identity(self.turn_id, field="turn_id")
        _require_identity(self.user_id, field="user_id")
        _require_identity(self.conversation_id, field="conversation_id")
        if self.status not in _ALLOWED and self.status not in TERMINAL_STATUSES:
            raise CoachTurnError(f"unknown turn status: {self.status!r}")
        if type(self.version) is not int or self.version < 1:
            raise CoachTurnError("version must be a positive integer")
        _require_aware(self.created_at, field="created_at")
        if self.cancel_requested_at is not None:
            _require_aware(self.cancel_requested_at, field="cancel_requested_at")
        if self.finished_at is not None:
            _require_aware(self.finished_at, field="finished_at")


def holds_slot(turn: TurnState) -> bool:
    return turn.status in SLOT_HOLDING_STATUSES


def is_stopping(turn: TurnState) -> bool:
    """Cancel requested, transport not closed. Still occupying the slot."""
    return turn.status == "running" and turn.cancel_requested_at is not None


def require_slot_free(turns: tuple[TurnState, ...] | list[TurnState]) -> None:
    """Refuse rather than queue: a queued turn would look accepted but never start."""
    for turn in turns:
        if holds_slot(turn):
            raise TurnSlotBusy(turn.turn_id)


def transition(
    turn: TurnState,
    target: TurnStatus,
    *,
    at: datetime,
    expected_version: int | None = None,
) -> TurnState:
    """Apply one legal move. Repeating a terminal state is a no-op, never a rewrite."""
    _require_aware(at, field="at")
    if target not in _ALLOWED and target not in TERMINAL_STATUSES:
        raise CoachTurnError(f"unknown turn status: {target!r}")
    if expected_version is not None:
        if type(expected_version) is not int or expected_version < 1:
            raise CoachTurnError("expected_version must be a positive integer")
        if expected_version != turn.version:
            raise TurnVersionConflict("the turn changed since it was read")

    if turn.status in TERMINAL_STATUSES:
        if target == turn.status:
            return turn
        if target == "cancelled":
            raise TurnNotCancellable("the turn has already finished")
        raise TurnVersionConflict("a terminal turn cannot change state")

    if target == turn.status:
        # Re-requesting a stop on an already stopping turn must not open a second
        # close: the first close still owns the transport.
        return turn

    if target not in _ALLOWED[turn.status]:
        raise TurnVersionConflict(f"cannot move {turn.status} to {target}")

    finished_at = at if target in TERMINAL_STATUSES else turn.finished_at
    return replace(
        turn,
        status=target,
        version=turn.version + 1,
        finished_at=finished_at,
    )


def request_cancel(turn: TurnState, *, at: datetime) -> TurnState:
    """Mark intent without releasing the slot.

    Returns the same turn when a stop is already pending, so a double click
    cannot produce two closes.
    """
    _require_aware(at, field="at")
    if turn.status in TERMINAL_STATUSES:
        raise TurnNotCancellable("the turn has already finished")
    if turn.cancel_requested_at is not None:
        return turn
    return replace(turn, cancel_requested_at=at, version=turn.version + 1)


def cancellation_notice(language: str) -> str:
    return CANCELLATION_NOTICE.get(language, CANCELLATION_NOTICE["en-US"])
