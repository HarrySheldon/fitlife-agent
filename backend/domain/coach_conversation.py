"""Coach conversation contracts: ownership-neutral visibility, expiry and context window.

This module holds the pure rules. It never reads a database and never trusts a
browser-supplied identity: every helper that could expose another account's text
takes the conversation explicitly and filters on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

RETENTION_DAYS = 90
"""A message is visible strictly inside this window; exactly 90 days is expired."""

MAX_CONTEXT_ROUNDS = 6
"""At most this many complete, unexpired rounds are replayed into one model call."""

CONTEXT_CHARACTER_BUDGET = 4000
"""Upper bound on the projected text of one conversation context."""

TITLE_MAX_CHARS = 40

ConversationStatus = Literal["active", "deleted"]
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
MessageRole = Literal["user", "coach"]
ReviewStatus = Literal["pending", "approved", "rejected"]

TERMINAL_TURN_STATUSES: frozenset[str] = frozenset(
    {"succeeded", "failed", "cancelled", "interrupted", "expired"}
)
"""Terminal states release the single execution slot. A closed browser does not."""

_ROLES: frozenset[str] = frozenset({"user", "coach"})
_REVIEW_STATUSES: frozenset[str] = frozenset({"pending", "approved", "rejected"})


class CoachConversationError(ValueError):
    pass


def _require_aware(value: datetime, *, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field} requires an aware timestamp")


def _require_identity(value: str, *, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CoachConversationError(f"{field} is required")


def message_visible(created_at: datetime, now: datetime) -> bool:
    if created_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("Aware timestamps required")
    return now - timedelta(days=RETENTION_DAYS) < created_at <= now


@dataclass(frozen=True)
class CoachMessage:
    """One stored message. ``created_at`` and ``review_status`` are server-produced."""

    message_id: str
    conversation_id: str
    turn_id: str
    role: MessageRole
    body: str
    created_at: datetime
    review_status: ReviewStatus = "approved"
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identity(self.message_id, field="message_id")
        _require_identity(self.conversation_id, field="conversation_id")
        _require_identity(self.turn_id, field="turn_id")
        if not isinstance(self.body, str) or not self.body.strip():
            raise CoachConversationError("message body must not be blank")
        if self.role not in _ROLES:
            raise CoachConversationError(f"unknown message role: {self.role!r}")
        if self.review_status not in _REVIEW_STATUSES:
            raise CoachConversationError(
                f"unknown review status: {self.review_status!r}"
            )
        _require_aware(self.created_at, field="created_at")


@dataclass(frozen=True)
class ContextMessage:
    role: MessageRole
    body: str
    admitted_scope: bool = False
    context_ref: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ContextProjection:
    """What one turn is allowed to replay. Never a summary, never another chat."""

    messages: tuple[ContextMessage, ...]
    rounds: int
    characters: int


def visible_messages(
    messages: tuple[CoachMessage, ...], *, conversation_id: str, now: datetime
) -> tuple[CoachMessage, ...]:
    """Keep only unexpired messages of the requested conversation, in stored order."""
    _require_identity(conversation_id, field="conversation_id")
    _require_aware(now, field="now")
    return tuple(
        message
        for message in messages
        if message.conversation_id == conversation_id
        and message_visible(message.created_at, now)
    )


def turn_is_terminal(status: str) -> bool:
    if status not in TERMINAL_TURN_STATUSES and status not in {
        "queued",
        "running",
        "awaiting_user",
    }:
        raise CoachConversationError(f"unknown turn status: {status!r}")
    return status in TERMINAL_TURN_STATUSES


def derive_conversation_title(text: str) -> str | None:
    """An empty or whitespace-only first message clears the title instead of storing it."""
    if not isinstance(text, str):
        raise CoachConversationError("title source must be text")
    collapsed = " ".join(text.split())
    if not collapsed:
        return None
    return collapsed[:TITLE_MAX_CHARS]


def project_context(
    messages: tuple[CoachMessage, ...],
    *,
    conversation_id: str,
    now: datetime,
    max_rounds: int = MAX_CONTEXT_ROUNDS,
    character_budget: int = CONTEXT_CHARACTER_BUDGET,
) -> ContextProjection:
    """Replay the most recent complete rounds that fit the remaining budget.

    A round is a user message plus the reviewed coach message that answered it.
    Unreviewed coach text never enters context, and an unreviewed answer consumes
    its user message so a stale question cannot pair with a later reply.
    """
    if type(max_rounds) is not int or max_rounds < 1:
        raise CoachConversationError("max_rounds must be a positive integer")
    if type(character_budget) is not int or character_budget < 1:
        raise CoachConversationError("character_budget must be a positive integer")

    ordered = sorted(
        visible_messages(messages, conversation_id=conversation_id, now=now),
        # Within the same instant the question still precedes its answer, so a
        # coarse clock cannot invert a round.
        key=lambda message: (
            message.created_at,
            0 if message.role == "user" else 1,
            message.message_id,
        ),
    )

    rounds: list[tuple[CoachMessage, CoachMessage]] = []
    pending: CoachMessage | None = None
    for message in ordered:
        if message.role == "user":
            pending = message
            continue
        if pending is None:
            continue
        answered = message.review_status == "approved"
        if answered:
            rounds.append((pending, message))
        pending = None

    selected = rounds[-max_rounds:]

    def characters_of(selection: list[tuple[CoachMessage, CoachMessage]]) -> int:
        return sum(
            len(message.body) for pair in selection for message in pair
        )

    while selected and characters_of(selected) > character_budget:
        selected.pop(0)

    projection = tuple(
        ContextMessage(role=message.role, body=message.body,
            admitted_scope=pair[1].metadata.get("context", {}).get("admitted_scope") is True,
            context_ref=pair[1].metadata.get("context", {}))
        for pair in selected
        for message in pair
    )
    return ContextProjection(
        messages=projection,
        rounds=len(selected),
        characters=characters_of(selected),
    )
