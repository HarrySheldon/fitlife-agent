from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FailureCategory(str, Enum):
    TRANSIENT = "transient"
    AUTHENTICATION = "authentication"
    INVALID_INPUT = "invalid_input"
    QUOTA = "quota"
    SAFETY = "safety"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    BUDGET = "budget"
    INTERNAL = "internal"


class Disposition(str, Enum):
    RETRY = "retry"
    FALLBACK = "fallback"
    ASK_USER = "ask_user"
    REFUSE = "refuse"
    CANCEL = "cancel"
    FAIL = "fail"


@dataclass(frozen=True)
class RuntimeFailure:
    code: str
    category: FailureCategory
    stage: str
    retryable: bool
    attempt: int
    safe_message_key: str
    cause: Exception | None = None
    provider_status: int | None = None
    retry_after_seconds: float | None = None

    def to_public_fields(self) -> dict[str, object]:
        return {"code": self.code, "retryable": self.retryable}


def classify_failure(error: Exception, *, stage: str, attempt: int) -> RuntimeFailure:
    status = getattr(error, "status_code", None)
    code = str(getattr(error, "code", "") or "").lower()
    name = type(error).__name__.lower()
    retry_after = getattr(error, "retry_after", None)
    if retry_after is None and getattr(error, "retry_after_ms", None) is not None:
        retry_after = float(error.retry_after_ms) / 1000
    if isinstance(error, (ConnectionError, ConnectionResetError)) or "connection" in name:
        return _failure("MODEL_CONNECTION_FAILED", FailureCategory.TRANSIENT, True, error, stage, attempt, status, retry_after)
    if isinstance(error, TimeoutError):
        return _failure("MODEL_TIMEOUT", FailureCategory.TIMEOUT, True, error, stage, attempt, status, retry_after)
    if status in (401, 403):
        return _failure("MODEL_AUTH_FAILED", FailureCategory.AUTHENTICATION, False, error, stage, attempt, status, retry_after)
    if "quota" in code or "billing" in code:
        return _failure("MODEL_QUOTA_EXHAUSTED", FailureCategory.QUOTA, False, error, stage, attempt, status, retry_after)
    if "safety" in code or "content_filter" in code:
        return _failure("MODEL_SAFETY_REFUSAL", FailureCategory.SAFETY, False, error, stage, attempt, status, retry_after)
    if "model_not_found" in code or (status == 404 and "model" in code):
        return _failure("MODEL_NOT_FOUND", FailureCategory.INVALID_INPUT, False, error, stage, attempt, status, retry_after)
    transient = status in (408, 429) or (status == 409 and code in ("conflict", "recoverable_conflict")) or (isinstance(status, int) and 500 <= status <= 599 and status not in (501, 505))
    if transient:
        return _failure("MODEL_TRANSIENT_ERROR", FailureCategory.TRANSIENT, True, error, stage, attempt, status, retry_after)
    if status is not None and 400 <= status < 500:
        return _failure("MODEL_INVALID_REQUEST", FailureCategory.INVALID_INPUT, False, error, stage, attempt, status, retry_after)
    return _failure("INTERNAL_ERROR", FailureCategory.INTERNAL, False, error, stage, attempt, status, retry_after)


def decide_disposition(failure: RuntimeFailure) -> Disposition:
    if failure.retryable:
        return Disposition.RETRY
    if failure.category is FailureCategory.SAFETY:
        return Disposition.REFUSE
    if failure.category in (FailureCategory.AUTHENTICATION, FailureCategory.INVALID_INPUT):
        return Disposition.ASK_USER
    if failure.category is FailureCategory.CANCELLED:
        return Disposition.CANCEL
    return Disposition.FAIL


def _failure(code, category, retryable, cause, stage, attempt, status, retry_after):
    return RuntimeFailure(code, category, stage, retryable, attempt, code, cause, status, retry_after)
