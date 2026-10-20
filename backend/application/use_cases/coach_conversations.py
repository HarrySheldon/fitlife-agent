"""Coach conversation use cases.

This layer owns *requests*: creating, reading and deleting a chat, and deciding
how much history one turn may replay. It never becomes a second planner and it
never stores business state: a plan, a meal or a target still lives in its own
repository, and a chat only ever holds a reference to it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from backend.application.ports.coach_conversation_repository import (
    CoachConversationRepository,
    ConversationRecord,
)
from backend.domain.coach_conversation import (
    CONTEXT_CHARACTER_BUDGET,
    MAX_CONTEXT_ROUNDS,
    CoachMessage,
    ContextProjection,
    project_context,
)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("An aware timestamp is required")
    return value.astimezone(timezone.utc)


def _owner(user_id: str) -> str:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("An explicit owner is required")
    return user_id


class CoachConversations:
    def __init__(
        self,
        repository: CoachConversationRepository,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.repository = repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.id_factory = id_factory or (lambda: uuid4().hex)

    def create(self, user_id: str, *, title: str | None = None) -> ConversationRecord:
        """The id and the timestamp are server-generated; the client supplies only text."""
        return self.repository.create_conversation(
            _owner(user_id),
            conversation_id=self.id_factory(),
            title=title,
            created_at=_utc(self.clock()),
        )

    def list(
        self, user_id: str, *, limit: int = 50, before: datetime | None = None
    ) -> tuple[ConversationRecord, ...]:
        return self.repository.list_conversations(
            _owner(user_id),
            limit=limit,
            before=None if before is None else _utc(before),
        )

    def get(self, user_id: str, conversation_id: str) -> ConversationRecord:
        return self.repository.get_conversation(_owner(user_id), conversation_id)

    def rename(
        self, user_id: str, conversation_id: str, *, title: str | None
    ) -> ConversationRecord:
        return self.repository.rename_conversation(
            _owner(user_id), conversation_id, title=title, updated_at=_utc(self.clock())
        )

    def delete(self, user_id: str, conversation_id: str) -> bool:
        return self.repository.delete_conversation(
            _owner(user_id), conversation_id, deleted_at=_utc(self.clock())
        )

    def messages(
        self, user_id: str, conversation_id: str, *, now: datetime | None = None
    ) -> tuple[CoachMessage, ...]:
        return self.repository.list_messages(
            _owner(user_id),
            conversation_id,
            now=_utc(now or self.clock()),
        )

    def context(
        self,
        user_id: str,
        *,
        conversation_id: str,
        turn_id: str,
        character_budget: int = CONTEXT_CHARACTER_BUDGET,
        max_rounds: int = MAX_CONTEXT_ROUNDS,
        now: datetime | None = None,
    ) -> ContextProjection:
        """Project the history one turn may see.

        Only this conversation, only complete rounds whose question is inside the
        window, never the in-flight turn itself, and never more than the remaining
        budget. No summary is generated and no other chat is read.
        """
        if type(character_budget) is not int or character_budget < 0:
            raise ValueError("character_budget must be a nonnegative integer")
        if not isinstance(turn_id, str) or not turn_id.strip():
            raise ValueError("An explicit turn is required")

        moment = _utc(now or self.clock())
        messages = self.repository.list_messages(
            _owner(user_id), conversation_id, now=moment
        )
        history = tuple(
            message for message in messages if message.turn_id != turn_id
        )
        if character_budget == 0 or not history:
            return ContextProjection(messages=(), rounds=0, characters=0)
        return project_context(
            history,
            conversation_id=conversation_id,
            now=moment,
            max_rounds=max_rounds,
            character_budget=character_budget,
        )
