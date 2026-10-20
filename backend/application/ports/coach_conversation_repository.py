"""Owner-scoped coach conversation persistence.

Every method that reads or mutates account data takes ``user_id`` explicitly.
No caller may take the owner from a request body, and no query may be built
without it: the conversation, the turn and every message are addressed by
``(user_id, ...)`` together. ``purge_expired`` is the single exception because
it is a maintenance sweep that returns only a row count.

Message timestamps, roles and review status are produced by the server. A client
can supply text; it cannot supply who said it or when.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from backend.domain.coach_conversation import (
    CoachMessage,
    ConversationStatus,
    TurnStatus,
)


@dataclass(frozen=True)
class ConversationRecord:
    conversation_id: str
    user_id: str
    title: str | None
    status: ConversationStatus
    created_at: datetime
    updated_at: datetime
    kind: str = "user"
    """``system`` holds legacy quick-action turns; it is never listed or exported."""


@dataclass(frozen=True)
class TurnRecord:
    turn_id: str
    conversation_id: str
    user_id: str
    idempotency_key: str
    request_fingerprint: str
    status: TurnStatus
    created_at: datetime
    version: int = 1
    cancel_requested_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    slot_released_at: datetime | None = None
    lease_id: str | None = None
    receipt_json: str | None = None
    error_code: str | None = None


class CoachConversationConflict(ValueError):
    code = "IDEMPOTENCY_CONFLICT"


class CoachConversationDeleted(ValueError):
    """The conversation left the active lifecycle; nothing may be published to it."""

    code = "CONVERSATION_DELETED"


class CoachConversationRepository(Protocol):
    def create_conversation(
        self,
        user_id: str,
        *,
        conversation_id: str,
        title: str | None,
        created_at: datetime,
        kind: str = "user",
    ) -> ConversationRecord: ...

    def list_conversations(
        self,
        user_id: str,
        *,
        limit: int = 50,
        before: datetime | None = None,
    ) -> tuple[ConversationRecord, ...]: ...

    def get_conversation(self, user_id: str, conversation_id: str) -> ConversationRecord: ...

    def rename_conversation(
        self,
        user_id: str,
        conversation_id: str,
        *,
        title: str | None,
        updated_at: datetime,
    ) -> ConversationRecord: ...

    def delete_conversation(
        self, user_id: str, conversation_id: str, *, deleted_at: datetime
    ) -> bool: ...

    def accept_turn(
        self,
        user_id: str,
        conversation_id: str,
        *,
        turn_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        created_at: datetime,
        request_context: dict | None = None,
    ) -> TurnRecord:
        """Atomic admission: idempotent on the key, and refuses a second slot holder.

        Raises ``TurnSlotBusy`` rather than queueing. A queued turn would look
        accepted to the caller while nothing was going to start it.
        """
        ...

    def get_turn(self, user_id: str, turn_id: str) -> TurnRecord: ...

    def claim_turn(
        self,
        user_id: str,
        turn_id: str,
        *,
        lease_id: str,
        started_at: datetime,
        expected_version: int | None = None,
    ) -> TurnRecord:
        """Take execution ownership. Only an already accepted turn may be claimed."""
        ...

    def request_cancel(
        self, user_id: str, turn_id: str, *, at: datetime
    ) -> TurnRecord:
        """Record intent. The status stays ``running`` until the transport closes."""
        ...

    def release_slot(
        self, user_id: str, turn_id: str, *, at: datetime
    ) -> TurnRecord:
        """Move a turn to ``awaiting_user``: the model is done, the user must answer."""
        ...

    def publish_turn(
        self,
        user_id: str,
        turn_id: str,
        *,
        status: TurnStatus,
        updated_at: datetime,
        expected_version: int | None = None,
        receipt_json: str | None = None,
        error_code: str | None = None,
    ) -> bool:
        """Publish one terminal state, once, under every ownership precondition.

        Returns False when the turn may no longer be published — the conversation
        was deleted, the turn was cancelled, it expired, the version moved, or the
        answer was not reviewed. The caller discards the late result.
        """
        ...

    def complete_turn(
        self,
        user_id: str,
        turn_id: str,
        *,
        message: CoachMessage,
        updated_at: datetime,
        expected_version: int | None = None,
        receipt_json: str | None = None,
    ) -> bool:
        """Store the answer and finish the turn in one transaction.

        Two transactions would leave a window: the answer is written, the cancel
        lands, and the turn stays open holding text the user already stopped.
        Here the answer exists only if the turn was still publishable at the
        instant it was written.
        """
        ...

    def active_turn(self, user_id: str) -> TurnRecord | None:
        """The turn holding the single execution slot, if any."""
        ...

    def interrupt_stale_turns(
        self, live_lease_ids: tuple[str, ...], *, at: datetime
    ) -> int:
        """Mark unrecoverable in-flight turns as interrupted. Never resend them."""
        ...

    def append_message(self, user_id: str, message: CoachMessage) -> CoachMessage: ...

    def list_messages(
        self,
        user_id: str,
        conversation_id: str,
        *,
        now: datetime,
        limit: int = 200,
    ) -> tuple[CoachMessage, ...]: ...

    def purge_expired(self, now: datetime) -> int: ...


class CoachConversationExportPort(Protocol):
    """Account-scoped snapshot and erasure, used by export and account deletion."""

    def export_conversations(
        self, user_id: str, *, max_bytes: int, now: datetime | None = None
    ) -> bytes:
        """Only what the app would still show: active chats, unexpired text."""
        ...

    def delete_user_data(self, user_id: str) -> None: ...
