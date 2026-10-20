"""Owner-scoped coach conversation storage.

Two invariants are enforced by the schema rather than by convention:

* ``(conversation_id, user_id)`` is a composite key, so a message or turn cannot
  be attached to another account's conversation even by a buggy caller.
* Messages of a round are only readable while the *question* is inside the
  90-day window, so a derived answer never outlives what it answered.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from backend.application.ports.coach_conversation_repository import (
    CoachConversationConflict,
    CoachConversationDeleted,
    ConversationRecord,
    TurnRecord,
)
from backend.domain.coach_conversation import (
    RETENTION_DAYS,
    TERMINAL_TURN_STATUSES,
    CoachMessage,
    derive_conversation_title,
)
from backend.domain.coach_turn import (
    TurnNotCancellable,
    TurnSlotBusy,
    TurnState,
    TurnVersionConflict,
    transition,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase

_ACTIVE = "active"
_SLOT_HOLDERS = ("queued", "running")
_MAX_VERSION = 2**31 - 1


def _stamp(value: datetime, *, field: str) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field} requires an aware timestamp")
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _parse(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _identity(*values: str) -> None:
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("identity is required")


def _limit(value: int, *, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError("limit is out of range")
    return value


def _conversation(row: sqlite3.Row) -> ConversationRecord:
    return ConversationRecord(
        conversation_id=row["conversation_id"],
        user_id=row["user_id"],
        title=row["title"],
        status=row["status"],
        created_at=_parse(row["created_at"]),
        updated_at=_parse(row["updated_at"]),
        kind=row["kind"],
    )


def _turn(row: sqlite3.Row) -> TurnRecord:
    return TurnRecord(
        turn_id=row["turn_id"],
        conversation_id=row["conversation_id"],
        user_id=row["user_id"],
        idempotency_key=row["idempotency_key"],
        request_fingerprint=row["request_fingerprint"],
        status=row["status"],
        created_at=_parse(row["created_at"]),
        version=row["version"],
        cancel_requested_at=_optional(row["cancel_requested_at"]),
        started_at=_optional(row["started_at"]),
        finished_at=_optional(row["finished_at"]),
        slot_released_at=_optional(row["slot_released_at"]),
        lease_id=row["lease_id"],
        receipt_json=row["receipt_json"],
        error_code=row["error_code"],
    )


def _optional(text: str | None) -> datetime | None:
    return None if text is None else _parse(text)


def _state(turn: TurnRecord) -> TurnState:
    return TurnState(
        turn_id=turn.turn_id,
        user_id=turn.user_id,
        conversation_id=turn.conversation_id,
        status=turn.status,
        version=turn.version,
        created_at=turn.created_at,
        cancel_requested_at=turn.cancel_requested_at,
        finished_at=turn.finished_at,
    )


def _message(row: sqlite3.Row) -> CoachMessage:
    from backend.domain.coach_message_metadata import public_message_metadata
    return CoachMessage(
        message_id=row["message_id"],
        conversation_id=row["conversation_id"],
        turn_id=row["turn_id"],
        role=row["role"],
        body=row["body"],
        created_at=_parse(row["created_at"]),
        review_status=row["review_status"],
        metadata=public_message_metadata(row["receipt_json"]) if "receipt_json" in row.keys() and row["role"] == "coach" else {},
    )


class SQLiteCoachConversationRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    # -- conversations ---------------------------------------------------
    def create_conversation(
        self,
        user_id: str,
        *,
        conversation_id: str,
        title: str | None,
        created_at: datetime,
        kind: str = "user",
    ) -> ConversationRecord:
        _identity(user_id, conversation_id)
        if kind not in {"user", "system"}:
            raise ValueError("unknown conversation kind")
        stamp = _stamp(created_at, field="created_at")
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO coach_conversations(
                        conversation_id, user_id, title, status, created_at,
                        updated_at, kind
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        conversation_id,
                        user_id,
                        derive_conversation_title(title or ""),
                        _ACTIVE,
                        stamp,
                        stamp,
                        kind,
                    ),
                )
                return self._require_conversation(connection, user_id, conversation_id)
        except sqlite3.IntegrityError:
            raise CoachConversationConflict("conversation already exists") from None

    def list_conversations(
        self,
        user_id: str,
        *,
        limit: int = 50,
        before: datetime | None = None,
    ) -> tuple[ConversationRecord, ...]:
        _identity(user_id)
        bound = _limit(limit, maximum=200)
        cutoff = None if before is None else _stamp(before, field="before")
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM coach_conversations
                WHERE user_id = ? AND status = ? AND kind = 'user'
                  AND (? IS NULL OR updated_at < ?)
                ORDER BY updated_at DESC, conversation_id DESC
                LIMIT ?
                """,
                (user_id, _ACTIVE, cutoff, cutoff, bound),
            ).fetchall()
        return tuple(_conversation(row) for row in rows)

    def get_conversation(self, user_id: str, conversation_id: str) -> ConversationRecord:
        _identity(user_id, conversation_id)
        with self.database.connection() as connection:
            return self._require_conversation(connection, user_id, conversation_id)

    def rename_conversation(
        self,
        user_id: str,
        conversation_id: str,
        *,
        title: str | None,
        updated_at: datetime,
    ) -> ConversationRecord:
        _identity(user_id, conversation_id)
        stamp = _stamp(updated_at, field="updated_at")
        with self.database.transaction() as connection:
            updated = connection.execute(
                """
                UPDATE coach_conversations
                SET title = ?, updated_at = ?
                WHERE conversation_id = ? AND user_id = ? AND status = ?
                """,
                (
                    derive_conversation_title(title or ""),
                    stamp,
                    conversation_id,
                    user_id,
                    _ACTIVE,
                ),
            ).rowcount
            if updated != 1:
                raise KeyError(conversation_id)
            return self._require_conversation(connection, user_id, conversation_id)

    def delete_conversation(
        self, user_id: str, conversation_id: str, *, deleted_at: datetime
    ) -> bool:
        """Soft delete: the row must survive so a late model result can be rejected."""
        _identity(user_id, conversation_id)
        stamp = _stamp(deleted_at, field="deleted_at")
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT status FROM coach_conversations
                WHERE conversation_id = ? AND user_id = ?
                """,
                (conversation_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError(conversation_id)
            if row["status"] != _ACTIVE:
                return False
            connection.execute(
                """
                UPDATE coach_conversations
                SET status = 'deleted', deleted_at = ?, updated_at = ?
                WHERE conversation_id = ? AND user_id = ? AND status = ?
                """,
                (stamp, stamp, conversation_id, user_id, _ACTIVE),
            )
            # A tombstone hides the transcript immediately, but cannot prove that
            # the worker has closed its transport. Only that worker (or startup
            # recovery after process death) may release the execution slot.
            connection.execute(
                f"""
                UPDATE coach_turns
                SET cancel_requested_at = COALESCE(cancel_requested_at, ?), updated_at = ?
                WHERE conversation_id = ? AND user_id = ?
                  AND status IN ({", ".join("?" for _ in _SLOT_HOLDERS)})
                """,
                (stamp, stamp, conversation_id, user_id, *_SLOT_HOLDERS),
            )
            return True

    # -- turns -----------------------------------------------------------
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
        """Idempotent admission under the single slot, in one write transaction.

        The duplicate check comes first so a retry of the same request returns the
        original turn even while that turn still holds the slot. A different key
        that arrives while the slot is held is refused, not queued.
        """
        _identity(user_id, conversation_id, turn_id, idempotency_key, request_fingerprint)
        stamp = _stamp(created_at, field="created_at")
        with self.database.transaction() as connection:
            self._require_conversation(connection, user_id, conversation_id)
            existing = connection.execute(
                """
                SELECT * FROM coach_turns
                WHERE user_id = ? AND conversation_id = ? AND idempotency_key = ?
                """,
                (user_id, conversation_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["request_fingerprint"] != request_fingerprint:
                    raise CoachConversationConflict("idempotency key was reused")
                return _turn(existing)
            holder = connection.execute(
                """
                SELECT t.turn_id FROM coach_turns t
                JOIN coach_conversations c
                  ON c.conversation_id = t.conversation_id AND c.user_id = t.user_id
                WHERE t.user_id = ? AND t.status IN (?, ?)
                ORDER BY t.created_at
                LIMIT 1
                """,
                (user_id, *_SLOT_HOLDERS),
            ).fetchone()
            if holder is not None:
                raise TurnSlotBusy(holder["turn_id"])
            try:
                connection.execute(
                    """
                    INSERT INTO coach_turns(
                        turn_id, conversation_id, user_id, idempotency_key,
                        request_fingerprint, status, created_at, updated_at, version, receipt_json
                    ) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, 1, ?)
                    """,
                    (
                        turn_id,
                        conversation_id,
                        user_id,
                        idempotency_key,
                        request_fingerprint,
                        stamp,
                        stamp,
                        json.dumps({"context": request_context}, ensure_ascii=False) if request_context else None,
                    ),
                )
            except sqlite3.IntegrityError:
                raise CoachConversationConflict("turn already exists") from None
            return _turn(
                connection.execute(
                    "SELECT * FROM coach_turns WHERE turn_id = ? AND user_id = ?",
                    (turn_id, user_id),
                ).fetchone()
            )

    def get_turn(self, user_id: str, turn_id: str) -> TurnRecord:
        """Read one turn, but only while its conversation is still active.

        A turn of a deleted conversation is not readable: the chat is gone, so its
        transcript and its status are gone too. The service relies on this — a
        worker that finishes after a deletion gets ``KeyError`` and discards the
        answer instead of reviving the chat.
        """
        _identity(user_id, turn_id)
        with self.database.connection() as connection:
            turn = self._require_turn(connection, user_id, turn_id)
            row = connection.execute(
                "SELECT status FROM coach_conversations WHERE conversation_id = ? AND user_id = ?",
                (turn.conversation_id, user_id),
            ).fetchone()
            if row is None or row["status"] != _ACTIVE:
                raise KeyError(turn_id)
            return turn

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
        """Write the reviewed answer and finish the turn atomically.

        Every precondition is re-read here, inside the same transaction that
        inserts the message, so a cancel, a deletion or an expiry that lands
        during generation leaves no orphan answer behind.
        """
        _identity(user_id, turn_id)
        if message.role != "coach" or message.review_status != "approved":
            raise ValueError("only a reviewed coach answer may complete a turn")
        stamp = _stamp(updated_at, field="updated_at")
        with self.database.transaction() as connection:
            turn = self._require_turn(connection, user_id, turn_id)
            conversation = connection.execute(
                "SELECT status FROM coach_conversations WHERE conversation_id = ? AND user_id = ?",
                (turn.conversation_id, user_id),
            ).fetchone()
            if conversation is None or conversation["status"] != _ACTIVE:
                return False
            if turn.status in TERMINAL_TURN_STATUSES:
                return turn.status == "succeeded"
            if expected_version is not None and expected_version != turn.version:
                return False
            if turn.cancel_requested_at is not None:
                return False
            if updated_at - turn.created_at >= timedelta(days=RETENTION_DAYS):
                return False
            moved = transition(_state(turn), "succeeded", at=updated_at)
            connection.execute(
                """
                INSERT INTO coach_messages(
                    message_id, turn_id, conversation_id, user_id,
                    role, body, review_status, created_at
                ) VALUES (?, ?, ?, ?, 'coach', ?, 'approved', ?)
                """,
                (
                    message.message_id,
                    turn_id,
                    turn.conversation_id,
                    user_id,
                    message.body,
                    stamp,
                ),
            )
            connection.execute(
                """
                UPDATE coach_turns
                SET status = 'succeeded', version = ?, finished_at = ?,
                    slot_released_at = ?, receipt_json = COALESCE(?, receipt_json),
                    updated_at = ?
                WHERE turn_id = ? AND user_id = ? AND version = ?
                """,
                (
                    min(moved.version, _MAX_VERSION),
                    stamp,
                    stamp,
                    receipt_json,
                    stamp,
                    turn_id,
                    user_id,
                    turn.version,
                ),
            )
            return True

    def active_turn(self, user_id: str) -> TurnRecord | None:
        """The single slot holder, read-only. Never starts anything."""
        _identity(user_id)
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT t.* FROM coach_turns t
                JOIN coach_conversations c
                  ON c.conversation_id = t.conversation_id AND c.user_id = t.user_id
                WHERE t.user_id = ? AND t.status IN (?, ?)
                ORDER BY t.created_at
                LIMIT 1
                """,
                (user_id, *_SLOT_HOLDERS),
            ).fetchone()
        return None if row is None else _turn(row)

    def claim_turn(
        self,
        user_id: str,
        turn_id: str,
        *,
        lease_id: str,
        started_at: datetime,
        expected_version: int | None = None,
    ) -> TurnRecord:
        """queued -> running, stamped with the process that owns execution."""
        _identity(user_id, turn_id, lease_id)
        stamp = _stamp(started_at, field="started_at")
        with self.database.transaction() as connection:
            turn = self._require_turn(connection, user_id, turn_id)
            moved = transition(_state(turn), "running", at=started_at,
                               expected_version=expected_version)
            connection.execute(
                """
                UPDATE coach_turns
                SET status = ?, version = ?, started_at = ?, lease_id = ?, updated_at = ?
                WHERE turn_id = ? AND user_id = ? AND version = ?
                """,
                (moved.status, moved.version, stamp, lease_id, stamp, turn_id, user_id,
                 turn.version),
            )
            return self._require_turn(connection, user_id, turn_id)

    def request_cancel(self, user_id: str, turn_id: str, *, at: datetime) -> TurnRecord:
        """Set intent only. The status stays ``running`` so the slot stays taken."""
        _identity(user_id, turn_id)
        stamp = _stamp(at, field="at")
        with self.database.transaction() as connection:
            turn = self._require_turn(connection, user_id, turn_id)
            if turn.status in TERMINAL_TURN_STATUSES:
                raise TurnNotCancellable("the turn has already finished")
            if turn.cancel_requested_at is not None:
                return turn
            connection.execute(
                """
                UPDATE coach_turns
                SET cancel_requested_at = ?, version = version + 1, updated_at = ?
                WHERE turn_id = ? AND user_id = ? AND version = ?
                """,
                (stamp, stamp, turn_id, user_id, turn.version),
            )
            return self._require_turn(connection, user_id, turn_id)

    def release_slot(self, user_id: str, turn_id: str, *, at: datetime) -> TurnRecord:
        """running -> awaiting_user. The model is finished; the user is not."""
        _identity(user_id, turn_id)
        stamp = _stamp(at, field="at")
        with self.database.transaction() as connection:
            turn = self._require_turn(connection, user_id, turn_id)
            moved = transition(_state(turn), "awaiting_user", at=at)
            connection.execute(
                """
                UPDATE coach_turns
                SET status = ?, version = ?, slot_released_at = ?, updated_at = ?
                WHERE turn_id = ? AND user_id = ? AND version = ?
                """,
                (moved.status, moved.version, stamp, stamp, turn_id, user_id, turn.version),
            )
            return self._require_turn(connection, user_id, turn_id)

    def publish_turn(
        self,
        user_id: str,
        turn_id: str,
        *,
        status: str,
        updated_at: datetime,
        expected_version: int | None = None,
        receipt_json: str | None = None,
        error_code: str | None = None,
    ) -> bool:
        """Publish one terminal state, once, under every ownership precondition.

        Returns False when the conversation was deleted, the turn was cancelled,
        it expired, the version moved, or the answer was never reviewed. The
        caller then discards the late result instead of reviving it.
        """
        _identity(user_id, turn_id)
        if status not in TERMINAL_TURN_STATUSES:
            raise ValueError("only terminal turn states may be published")
        stamp = _stamp(updated_at, field="updated_at")
        with self.database.transaction() as connection:
            turn = self._require_turn(connection, user_id, turn_id)
            conversation = connection.execute(
                "SELECT status FROM coach_conversations WHERE conversation_id = ? AND user_id = ?",
                (turn.conversation_id, user_id),
            ).fetchone()
            gone = conversation is None or conversation["status"] != _ACTIVE
            if gone and status == "succeeded":
                return False
            # Deleting a chat must still release the slot: otherwise a stopped turn
            # would keep the account blocked forever with no way to clear it.
            if gone and status in {"cancelled", "interrupted", "expired"}:
                if turn.status in TERMINAL_TURN_STATUSES:
                    return turn.status == status
                connection.execute(
                    """
                    UPDATE coach_turns
                    SET status = ?, version = version + 1, finished_at = ?,
                        slot_released_at = ?, updated_at = ?
                    WHERE turn_id = ? AND user_id = ? AND version = ?
                    """,
                    (status, stamp, stamp, stamp, turn_id, user_id, turn.version),
                )
                return True
            if turn.status in TERMINAL_TURN_STATUSES:
                return turn.status == status
            if expected_version is not None and expected_version != turn.version:
                return False
            # A cancel that landed before publication wins: a late answer must not
            # overwrite the stop the user asked for.
            if turn.cancel_requested_at is not None and status == "succeeded":
                return False
            if status == "succeeded":
                if updated_at - turn.created_at >= timedelta(days=RETENTION_DAYS):
                    return False
                approved = connection.execute(
                    """
                    SELECT 1 FROM coach_messages
                    WHERE turn_id = ? AND user_id = ? AND role = 'coach'
                      AND review_status = 'approved'
                    LIMIT 1
                    """,
                    (turn_id, user_id),
                ).fetchone()
                if approved is None:
                    # Fail closed: an unreviewed answer is not a publishable answer.
                    return False
            moved = transition(_state(turn), status, at=updated_at)
            connection.execute(
                """
                UPDATE coach_turns
                SET status = ?, version = ?, finished_at = ?, slot_released_at = ?,
                    receipt_json = COALESCE(?, receipt_json),
                    error_code = ?, updated_at = ?
                WHERE turn_id = ? AND user_id = ? AND version = ?
                """,
                (
                    moved.status,
                    min(moved.version, _MAX_VERSION),
                    stamp,
                    stamp,
                    receipt_json,
                    error_code,
                    stamp,
                    turn_id,
                    user_id,
                    turn.version,
                ),
            )
            return True

    def interrupt_stale_turns(
        self, live_lease_ids: tuple[str, ...], *, at: datetime
    ) -> int:
        """Mark in-flight turns of other processes as interrupted.

        A restarted process cannot resume someone else's inference, so it says so
        instead of pretending the turn is still running. Nothing is resent.
        """
        stamp = _stamp(at, field="at")
        live = tuple(value for value in live_lease_ids if isinstance(value, str) and value.strip())
        placeholders = ",".join("?" for _ in live) or "''"
        with self.database.transaction() as connection:
            return connection.execute(
                f"""
                UPDATE coach_turns
                SET status = 'interrupted', version = version + 1, finished_at = ?,
                    slot_released_at = ?, updated_at = ?
                WHERE status IN (?, ?)
                  AND (lease_id IS NULL OR lease_id NOT IN ({placeholders}))
                """,
                (stamp, stamp, stamp, *_SLOT_HOLDERS, *live),
            ).rowcount

    # -- messages --------------------------------------------------------
    def append_message(self, user_id: str, message: CoachMessage) -> CoachMessage:
        _identity(user_id, message.message_id, message.conversation_id)
        stamp = _stamp(message.created_at, field="created_at")
        with self.database.transaction() as connection:
            conversation = connection.execute(
                "SELECT status FROM coach_conversations WHERE conversation_id = ? AND user_id = ?",
                (message.conversation_id, user_id),
            ).fetchone()
            if conversation is None:
                raise KeyError(message.conversation_id)
            if conversation["status"] != _ACTIVE:
                raise CoachConversationDeleted(message.conversation_id)
            turn = connection.execute(
                "SELECT turn_id FROM coach_turns WHERE turn_id = ? AND user_id = ?",
                (message.turn_id, user_id),
            ).fetchone()
            if turn is None:
                raise KeyError(message.turn_id)
            try:
                connection.execute(
                    """
                    INSERT INTO coach_messages(
                        message_id, turn_id, conversation_id, user_id,
                        role, body, review_status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message.message_id,
                        message.turn_id,
                        message.conversation_id,
                        user_id,
                        message.role,
                        message.body,
                        message.review_status,
                        stamp,
                    ),
                )
            except sqlite3.IntegrityError:
                raise CoachConversationConflict("message already exists") from None
            return message

    def list_messages(
        self,
        user_id: str,
        conversation_id: str,
        *,
        now: datetime,
        limit: int = 200,
    ) -> tuple[CoachMessage, ...]:
        """Read inside the 90-day window, before any background cleanup runs.

        A conversation that is not owned or no longer active is a 404, not an
        empty transcript: silence would let a deleted chat keep answering.
        """
        _identity(user_id, conversation_id)
        bound = _limit(limit, maximum=500)
        cutoff = _stamp(now - timedelta(days=RETENTION_DAYS), field="now")
        with self.database.connection() as connection:
            self._require_conversation(connection, user_id, conversation_id)
            rows = connection.execute(
                """
                SELECT m.*, t.receipt_json FROM coach_messages AS m
                LEFT JOIN coach_turns AS t ON t.turn_id = m.turn_id AND t.user_id = m.user_id
                JOIN coach_messages AS question
                  ON question.turn_id = m.turn_id AND question.role = 'user'
                WHERE m.user_id = ? AND m.conversation_id = ?
                  AND question.created_at > ? AND m.created_at > ?
                ORDER BY m.created_at,
                         CASE m.role WHEN 'user' THEN 0 ELSE 1 END,
                         m.message_id
                LIMIT ?
                """,
                (user_id, conversation_id, cutoff, cutoff, bound),
            ).fetchall()
        return tuple(_message(row) for row in rows)

    # -- lifecycle -------------------------------------------------------
    def export_conversations(
        self, user_id: str, *, max_bytes: int, now: datetime | None = None
    ) -> bytes:
        """Export what the app would still show: active chats, unexpired messages.

        Expired text is excluded rather than exported with a flag, because an
        export must not resurrect what the product already hides.
        """
        _identity(user_id)
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("max_bytes must be a positive integer")
        moment = now or datetime.now(timezone.utc)
        cutoff = _stamp(moment - timedelta(days=RETENTION_DAYS), field="now")
        with self.database.connection() as connection:
            conversations = connection.execute(
                """
                SELECT * FROM coach_conversations
                WHERE user_id = ? AND status = ? AND kind = 'user'
                ORDER BY created_at, conversation_id
                """,
                (user_id, _ACTIVE),
            ).fetchall()
            payload = []
            for conversation in conversations:
                rows = connection.execute(
                    """
                    SELECT m.* FROM coach_messages AS m
                    JOIN coach_messages AS question
                      ON question.turn_id = m.turn_id AND question.role = 'user'
                    WHERE m.user_id = ? AND m.conversation_id = ?
                      AND question.created_at > ? AND m.created_at > ?
                    ORDER BY m.created_at,
                         CASE m.role WHEN 'user' THEN 0 ELSE 1 END,
                         m.message_id
                    """,
                    (user_id, conversation["conversation_id"], cutoff, cutoff),
                ).fetchall()
                if not rows:
                    # Nothing is still visible, so neither the title nor the chat
                    # itself belongs in the export.
                    continue
                payload.append(
                    {
                        "conversation_id": conversation["conversation_id"],
                        "title": conversation["title"],
                        "created_at": conversation["created_at"],
                        "updated_at": conversation["updated_at"],
                        "messages": [
                            {
                                "message_id": row["message_id"],
                                "turn_id": row["turn_id"],
                                "role": row["role"],
                                "body": row["body"],
                                "review_status": row["review_status"],
                                "created_at": row["created_at"],
                            }
                            for row in rows
                        ],
                    }
                )
        serialized = json.dumps(
            {"conversations": payload}, ensure_ascii=False, sort_keys=True, indent=2
        ).encode("utf-8")
        if len(serialized) > max_bytes:
            raise ValueError("Coach conversation export exceeds the size limit")
        return serialized

    def delete_user_data(self, user_id: str) -> None:
        """Erase every chat of one account; turns and messages cascade."""
        _identity(user_id)
        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM coach_conversations WHERE user_id = ?", (user_id,)
            )

    def purge_expired(self, now: datetime) -> int:
        """Delete expired rounds. Repeating the sweep deletes nothing further."""
        cutoff = _stamp(now - timedelta(days=RETENTION_DAYS), field="now")
        with self.database.transaction() as connection:
            removed = connection.execute(
                """
                DELETE FROM coach_messages WHERE turn_id IN (
                    SELECT turn_id FROM coach_messages
                    WHERE role = 'user' AND created_at <= ?
                )
                """,
                (cutoff,),
            ).rowcount
            connection.execute(
                """
                DELETE FROM coach_turns
                WHERE turn_id NOT IN (SELECT turn_id FROM coach_messages)
                """
            )
        return removed

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _require_conversation(
        connection: sqlite3.Connection, user_id: str, conversation_id: str
    ) -> ConversationRecord:
        row = connection.execute(
            """
            SELECT * FROM coach_conversations
            WHERE conversation_id = ? AND user_id = ? AND status = ?
            """,
            (conversation_id, user_id, _ACTIVE),
        ).fetchone()
        if row is None:
            raise KeyError(conversation_id)
        return _conversation(row)

    @staticmethod
    def _require_turn(
        connection: sqlite3.Connection, user_id: str, turn_id: str
    ) -> TurnRecord:
        row = connection.execute(
            "SELECT * FROM coach_turns WHERE turn_id = ? AND user_id = ?",
            (turn_id, user_id),
        ).fetchone()
        if row is None:
            raise KeyError(turn_id)
        return _turn(row)
