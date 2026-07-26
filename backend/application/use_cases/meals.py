from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import datetime, timedelta, timezone
from uuid import UUID

from backend.application.ports.meal_repository import (
    ConfirmedMeal,
    MealDraft,
    MealDraftInput,
    MealRepository,
    MealRepositoryError,
)
from backend.domain.errors import ApplicationError


Clock = Callable[[], datetime]


class MealServiceError(ApplicationError):
    def __init__(self, code: str, *, status_code: int) -> None:
        super().__init__(
            code=code,
            message=code,
            status_code=status_code,
            processing_mode="deterministic",
        )


class MealService:
    def __init__(
        self,
        repository: MealRepository,
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
        payload: MealDraftInput,
    ) -> MealDraft:
        expires_at = _utc_timestamp(self._clock() + timedelta(days=30))
        with self._mutation_scope(user_id):
            try:
                return self.repository.create_draft(
                    user_id,
                    payload,
                    expires_at=expires_at,
                )
            except MealRepositoryError as error:
                raise _repository_error(error) from None

    def get_draft(self, user_id: str, draft_id: str) -> MealDraft | None:
        return self.repository.get_draft(user_id, draft_id)

    def update_draft(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        payload: MealDraftInput,
    ) -> MealDraft:
        with self._mutation_scope(user_id):
            try:
                return self.repository.update_draft(
                    user_id,
                    draft_id,
                    expected_version=expected_version,
                    payload=payload,
                )
            except MealRepositoryError as error:
                raise _repository_error(error) from None

    def delete_draft(self, user_id: str, draft_id: str) -> None:
        with self._mutation_scope(user_id):
            try:
                self.repository.delete_draft(user_id, draft_id)
            except MealRepositoryError as error:
                raise _repository_error(error) from None

    def confirm_draft(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
        timezone_name: str = "UTC",
    ) -> ConfirmedMeal:
        canonical_key = _require_uuid(idempotency_key)
        fingerprint = _fingerprint(
            {
                "draft_id": draft_id,
                "expected_version": expected_version,
                "user_id": user_id,
            }
        )
        with self._mutation_scope(user_id):
            try:
                return self.repository.confirm(
                    user_id,
                    draft_id,
                    expected_version=expected_version,
                    idempotency_key=canonical_key,
                    request_fingerprint=fingerprint,
                    timezone_name=timezone_name,
                )
            except MealRepositoryError as error:
                raise _repository_error(error) from None

    def list_meals(
        self,
        user_id: str,
        log_date: str,
    ) -> tuple[ConfirmedMeal, ...]:
        return self.repository.list_meals(user_id, log_date)


def _require_uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (AttributeError, TypeError, ValueError):
        raise MealServiceError(
            "INVALID_IDEMPOTENCY_KEY",
            status_code=422,
        ) from None


def _fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _repository_error(error: MealRepositoryError) -> MealServiceError:
    if error.code == "DRAFT_NOT_FOUND":
        status_code = 404
    elif error.code == "DRAFT_EXPIRED":
        status_code = 410
    elif error.code in {"DRAFT_VERSION_CONFLICT", "IDEMPOTENCY_KEY_REUSED"}:
        status_code = 409
    elif error.code in {
        "CUSTOM_FOOD_CREATE_FAILED",
        "DRAFT_UPDATE_FAILED",
        "MEAL_NOT_FOUND",
    }:
        status_code = 500
    else:
        status_code = 422
    return MealServiceError(error.code, status_code=status_code)


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )
