"""What one turn asks the model layer for, and what it is allowed to receive back.

The turn service owns admission, storage and publication. This port is only the
answer: no turn id, no conversation, no persistence. Keeping it that narrow is
what lets the cancellation test drive a synthetic slow transport without a
database, and lets the lifecycle tests run without a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from backend.domain.user_preferences import UserPreferences


@dataclass(frozen=True)
class CoachTurnRequest:
    user_id: str
    conversation_id: str
    turn_id: str
    question: str
    action: str
    surface: str
    date: str | None
    language: str
    answer_mode: str
    request_id: str
    preferences: UserPreferences = field(default_factory=UserPreferences)
    plan_id: str | None = None
    report_week: str | None = None


@dataclass(frozen=True)
class CoachTurnAnswer:
    answer_markdown: str
    model: str
    review_status: str = "approved"
    sources: tuple = ()
    trace: dict = field(default_factory=dict)


class CoachAnswerPort(Protocol):
    def run(self, request: CoachTurnRequest) -> CoachTurnAnswer:
        """Produce one answer. Must honour the abort registry in the context."""
        ...
