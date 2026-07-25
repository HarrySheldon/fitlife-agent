from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import datetime, timedelta, timezone
from uuid import UUID

from backend.application.ports.workout_repository import (
    ConfirmedWorkout,
    WorkoutDraft,
    WorkoutDraftInput,
    WorkoutRepository,
    WorkoutRepositoryError,
)
from backend.domain.errors import ApplicationError


Clock = Callable[[], datetime]


class WorkoutServiceError(ApplicationError):
    def __init__(self, code: str, *, status_code: int) -> None:
        super().__init__(
            code=code,
            message=code,
            status_code=status_code,
            processing_mode="deterministic",
        )


class WorkoutService:
    def __init__(
        self,
        repository: WorkoutRepository,
        *,
        clock: Clock | None = None,
        mutation_scope: Callable[[str], AbstractContextManager] | None = None,
    ) -> None:
        self.repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._mutation_scope = mutation_scope or (lambda _user_id: nullcontext())

    def create_draft(
        self,
        user_id: str,
        payload: WorkoutDraftInput,
    ) -> WorkoutDraft:
        expiry = _timestamp(self._clock() + timedelta(days=30))
        with self._mutation_scope(user_id):
            try:
                return self.repository.create_draft(
                    user_id,
                    payload,
                    expires_at=expiry,
                )
            except WorkoutRepositoryError as error:
                raise _error(error) from None

    def get_draft(self, user_id: str, draft_id: str) -> WorkoutDraft | None:
        return self.repository.get_draft(user_id, draft_id)

    def update_draft(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        payload: WorkoutDraftInput,
    ) -> WorkoutDraft:
        with self._mutation_scope(user_id):
            try:
                return self.repository.update_draft(
                    user_id,
                    draft_id,
                    expected_version=expected_version,
                    payload=payload,
                )
            except WorkoutRepositoryError as error:
                raise _error(error) from None

    def delete_draft(self, user_id: str, draft_id: str) -> None:
        with self._mutation_scope(user_id):
            try:
                self.repository.delete_draft(user_id, draft_id)
            except WorkoutRepositoryError as error:
                raise _error(error) from None

    def confirm_draft(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> ConfirmedWorkout:
        key = _uuid(idempotency_key)
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "draft_id": draft_id,
                    "expected_version": expected_version,
                    "user_id": user_id,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self._mutation_scope(user_id):
            try:
                return self.repository.confirm(
                    user_id,
                    draft_id,
                    expected_version=expected_version,
                    idempotency_key=key,
                    request_fingerprint=fingerprint,
                )
            except WorkoutRepositoryError as error:
                raise _error(error) from None

    def list_sessions(
        self,
        user_id: str,
        log_date: str,
    ) -> tuple[ConfirmedWorkout, ...]:
        return self.repository.list_sessions(user_id, log_date)


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (AttributeError, TypeError, ValueError):
        raise WorkoutServiceError(
            "INVALID_IDEMPOTENCY_KEY",
            status_code=422,
        ) from None


def _error(error: WorkoutRepositoryError) -> WorkoutServiceError:
    if error.code == "DRAFT_NOT_FOUND":
        status = 404
    elif error.code == "DRAFT_EXPIRED":
        status = 410
    elif error.code in {"DRAFT_VERSION_CONFLICT", "IDEMPOTENCY_KEY_REUSED"}:
        status = 409
    elif error.code in {"DRAFT_UPDATE_FAILED", "WORKOUT_NOT_FOUND"}:
        status = 500
    else:
        status = 422
    return WorkoutServiceError(error.code, status_code=status)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )
