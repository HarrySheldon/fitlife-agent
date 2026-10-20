"""HTTP surface of the conversation entry.

This module translates HTTP into one service call and back. It owns no lifecycle
rule: admission, the single slot, cancellation and publication all live in
``CoachTurnService`` and the repository, so a second entry cannot accidentally get
a different answer by going around them.

Two properties matter at this layer.

*Reading never executes.* Every ``GET`` maps to a repository read. There is no
path from a read to a model call, so a poll that arrives twice, or a client that
refreshes while a turn runs, cannot spend money.

*Errors stay redacted.* A failure returns a code and a public sentence. The
provider's message, the prompt and the draft never reach the client.

The entry is behind ``coach_conversations_enabled`` and defaults to off: C0's
answer-contract fix ships on the legacy endpoint and must not depend on a client
migrating to this one.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.api.dependencies import require_current_user
from backend.api.preference_context import preferences_for
from backend.api.utils import ok
from backend.application.ports.coach_conversation_repository import (
    CoachConversationConflict,
    ConversationRecord,
    TurnRecord,
)
from backend.application.use_cases.coach_turns import CoachTurnService
from backend.config import get_settings
from backend.domain.coach_answer import ACTION_REGISTRY, AnswerLanguage, resolve_language
from backend.domain.coach_turn import (
    TurnNotCancellable,
    TurnSlotBusy,
    cancellation_notice,
)
from backend.domain.errors import ApplicationError
from backend.domain.user_preferences import AppLanguage
from backend.infrastructure.agent_runtime.coach_answer_adapter import (
    RuntimeCoachAnswerAdapter,
)
from backend.infrastructure.repositories.sqlite_coach_conversation_repository import (
    SQLiteCoachConversationRepository,
)
from backend.infrastructure.sqlite.runtime import get_database
from backend.schemas import AuthenticatedUser, CoachSurface


router = APIRouter(prefix="/api/v1/coach")

CHAT_ACTION = "chat"
_ALLOWED_ACTIONS = frozenset(ACTION_REGISTRY) | {CHAT_ACTION}


# -- request bodies ------------------------------------------------------
class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=120)


class ConversationRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=120)


class ConversationTurnRequest(BaseModel):
    """What a client may say about a turn.

    Owner, role, timestamps and review status are absent on purpose: ``extra``
    rejects them, so a browser cannot claim to be someone else or to have spoken
    at a time of its choosing.
    """

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    action: str = CHAT_ACTION
    surface: CoachSurface = "today"
    date: str | None = None
    language: AppLanguage | None = None
    answer_mode: Literal["brief", "detailed"] | None = None
    plan_id: str | None = Field(default=None, pattern=r"^plan-[a-f0-9]{8,64}$")
    report_week: str | None = Field(default=None, pattern=r"^\d{4}-W\d{2}$")

    @model_validator(mode="after")
    def references_match_action(self):
        if self.plan_id is not None and (self.surface != "plan" or self.action != "adjust_next_plan"):
            raise ValueError("plan reference requires the plan explanation action")
        if self.report_week is not None and (self.surface != "review" or self.action != "explain_weekly_report"):
            raise ValueError("report reference requires the weekly explanation action")
        if self.surface == "plan" and self.action == "adjust_next_plan" and not self.plan_id:
            raise ValueError("a persisted plan reference is required")
        if self.action == "explain_weekly_report" and not self.report_week:
            raise ValueError("a persisted weekly report reference is required")
        return self

    @field_validator("action")
    @classmethod
    def _known_action(cls, value: str) -> str:
        if value not in _ALLOWED_ACTIONS:
            raise ValueError("unknown coach action")
        return value

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value


# -- service wiring ------------------------------------------------------
_SERVICES: dict[str, CoachTurnService] = {}


def _service_for_settings() -> CoachTurnService:
    settings = get_settings()
    key = str(settings.database_path)
    service = _SERVICES.get(key)
    if service is None:
        repository = SQLiteCoachConversationRepository(get_database())
        service = CoachTurnService(
            repository,
            RuntimeCoachAnswerAdapter(conversations=repository),
        )
        _SERVICES[key] = service
    return service


def get_coach_admission_service() -> CoachTurnService:
    """The single slot, for endpoints that must not bypass it.

    This is deliberately not gated by ``coach_conversations_enabled``: the legacy
    quick action, plan interpretation and weekly-report interpretation are already
    shipped, and they take the same slot whether or not the new chat entry is on.
    Turning the new entry off must not hand anyone a second concurrent model call.
    """
    return _service_for_settings()


def get_coach_turn_service() -> CoachTurnService:
    if not get_settings().coach_conversations_enabled:
        raise ApplicationError(
            code="COACH_CONVERSATIONS_DISABLED",
            message="The conversation entry is not enabled in this deployment.",
            status_code=409,
        )
    return _service_for_settings()


def reset_coach_turn_services() -> None:
    """Drop cached services. Used by tests and by a data-directory switch."""
    for service in _SERVICES.values():
        service.close()
    _SERVICES.clear()


# -- error translation ---------------------------------------------------
def _missing_conversation() -> ApplicationError:
    return ApplicationError(
        code="COACH_CONVERSATION_NOT_FOUND",
        message="That conversation no longer exists.",
        status_code=404,
    )


def _missing_turn() -> ApplicationError:
    return ApplicationError(
        code="COACH_TURN_NOT_FOUND",
        message="That turn no longer exists.",
        status_code=404,
    )


def _busy(error: TurnSlotBusy) -> ApplicationError:
    translated = ApplicationError(
        code="COACH_TURN_BUSY",
        message="Another answer is still running for this account.",
        status_code=409,
        action="Wait for it to finish or stop it, then ask again.",
    )
    translated.active_turn_id = error.active_turn_id
    return translated


def _not_cancellable() -> ApplicationError:
    return ApplicationError(
        code="TURN_NOT_CANCELLABLE",
        message="That answer has already finished.",
        status_code=409,
    )


def _conflict(error: CoachConversationConflict) -> ApplicationError:
    return ApplicationError(
        code="IDEMPOTENCY_CONFLICT",
        message="This request key was already used for a different request.",
        status_code=409,
    )


def coach_error(error: BaseException) -> ApplicationError:
    """Map a lifecycle refusal to the public shape. Unknown errors are not hidden."""
    if isinstance(error, TurnSlotBusy):
        return _busy(error)
    if isinstance(error, TurnNotCancellable):
        return _not_cancellable()
    if isinstance(error, CoachConversationConflict):
        return _conflict(error)
    if isinstance(error, KeyError):
        return _missing_conversation()
    raise error


# -- serialisation -------------------------------------------------------
def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _receipt(text: str | None) -> dict | None:
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _conversation_payload(record: ConversationRecord) -> dict:
    return {
        "conversation_id": record.conversation_id,
        "title": record.title,
        "created_at": _iso(record.created_at),
        "updated_at": _iso(record.updated_at),
    }


def _turn_payload(record: TurnRecord, *, replayed: bool = False) -> dict:
    return {
        "turn_id": record.turn_id,
        "conversation_id": record.conversation_id,
        "status": record.status,
        # ``stopping`` is derived, not stored: the transport is still open, so the
        # slot is still taken even though a stop has been requested.
        "stopping": record.status == "running" and record.cancel_requested_at is not None,
        "version": record.version,
        "created_at": _iso(record.created_at),
        "finished_at": _iso(record.finished_at),
        "cancel_requested_at": _iso(record.cancel_requested_at),
        "error_code": record.error_code,
        "receipt": _receipt(record.receipt_json),
        "replayed": replayed,
    }


def _message_payload(message) -> dict:
    return {
        "message_id": message.message_id,
        "turn_id": message.turn_id,
        "role": message.role,
        "body": message.body,
        "metadata": message.metadata,
        "created_at": _iso(message.created_at),
    }


def _answer_language(payload, user: AuthenticatedUser) -> AnswerLanguage:
    return resolve_language(
        requested=payload.language, account=preferences_for(user).language
    )


# -- conversations -------------------------------------------------------
@router.post("/conversations")
def create_conversation(
    payload: ConversationCreateRequest,
    user: AuthenticatedUser = Depends(require_current_user),
    service: CoachTurnService = Depends(get_coach_turn_service),
):
    record = service.repository.create_conversation(
        user.user_id,
        conversation_id=f"conv-{user.user_id[:8]}-{_nonce()}",
        title=payload.title,
        created_at=_now(service),
    )
    return ok(_conversation_payload(record))


@router.get("/conversations")
def list_conversations(
    user: AuthenticatedUser = Depends(require_current_user),
    service: CoachTurnService = Depends(get_coach_turn_service),
):
    records = service.repository.list_conversations(user.user_id)
    return ok({"conversations": [_conversation_payload(record) for record in records]})


@router.patch("/conversations/{conversation_id}")
def rename_conversation(
    conversation_id: str,
    payload: ConversationRenameRequest,
    user: AuthenticatedUser = Depends(require_current_user),
    service: CoachTurnService = Depends(get_coach_turn_service),
):
    try:
        record = service.repository.rename_conversation(
            user.user_id,
            conversation_id,
            title=payload.title,
            updated_at=_now(service),
        )
    except KeyError:
        raise _missing_conversation() from None
    return ok(_conversation_payload(record))


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
    service: CoachTurnService = Depends(get_coach_turn_service),
):
    # Deleting stops work first: the service cancels the turn that owns the slot,
    # then marks the conversation gone, so a late answer has nowhere to land.
    try:
        deleted = service.delete_conversation(user.user_id, conversation_id)
    except KeyError:
        raise _missing_conversation() from None
    if not deleted:
        raise _missing_conversation()
    return ok({"deleted": True})


@router.get("/conversations/{conversation_id}/messages")
def list_messages(
    conversation_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
    service: CoachTurnService = Depends(get_coach_turn_service),
):
    try:
        messages = service.repository.list_messages(
            user.user_id, conversation_id, now=_now(service)
        )
    except KeyError:
        raise _missing_conversation() from None
    return ok({"messages": [_message_payload(message) for message in messages]})


# -- turns ---------------------------------------------------------------
@router.post("/conversations/{conversation_id}/turns")
def start_turn(
    conversation_id: str,
    payload: ConversationTurnRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    user: AuthenticatedUser = Depends(require_current_user),
    service: CoachTurnService = Depends(get_coach_turn_service),
):
    if not idempotency_key.strip():
        raise ApplicationError(
            code="IDEMPOTENCY_KEY_REQUIRED",
            message="An Idempotency-Key header is required.",
            status_code=422,
        )
    try:
        submission = service.submit(
            user.user_id,
            conversation_id,
            idempotency_key=idempotency_key,
            question=payload.question,
            action=payload.action,
            surface=payload.surface,
            date=payload.date,
            language=_answer_language(payload, user),
            answer_mode=payload.answer_mode or "brief",
            preferences=preferences_for(user),
            plan_id=payload.plan_id, report_week=payload.report_week,
        )
    except KeyError:
        raise _missing_conversation() from None
    except TurnSlotBusy as error:
        raise _busy(error) from None
    except CoachConversationConflict as error:
        raise _conflict(error) from None
    return ok(_turn_payload(submission.turn, replayed=submission.replayed))


@router.get("/active-turn")
def read_active_turn(
    user: AuthenticatedUser = Depends(require_current_user),
    service: CoachTurnService = Depends(get_coach_turn_service),
):
    active = service.active(user.user_id)
    return ok({"turn": _turn_payload(active) if active is not None else None})


@router.get("/turns/{turn_id}")
def read_turn(
    turn_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
    service: CoachTurnService = Depends(get_coach_turn_service),
):
    try:
        record = service.repository.get_turn(user.user_id, turn_id)
    except KeyError:
        raise _missing_turn() from None
    return ok(_turn_payload(record))


@router.post("/turns/{turn_id}/cancel")
def cancel_turn(
    turn_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
    service: CoachTurnService = Depends(get_coach_turn_service),
):
    try:
        record = service.cancel(user.user_id, turn_id)
    except KeyError:
        raise _missing_turn() from None
    except TurnNotCancellable:
        raise _not_cancellable() from None
    payload = _turn_payload(record)
    # Said plainly rather than buried in a log: stopping work does not refund it.
    payload["notice"] = cancellation_notice(
        resolve_language(account=preferences_for(user).language)
    )
    return ok(payload)


def _now(service: CoachTurnService) -> datetime:
    return service.clock()


def _nonce() -> str:
    return uuid4().hex[:16]
