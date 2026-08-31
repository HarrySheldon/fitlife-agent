from __future__ import annotations

from backend.schemas import ProcessingMode


class ApplicationError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        processing_mode: ProcessingMode | None = None,
        message_key: str | None = None,
        action: str | None = None,
        retryable: bool = False,
        retry_after_ms: int | None = None,
        run_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.processing_mode = processing_mode
        self.message_key = message_key or code
        self.action = action
        self.retryable = retryable
        self.retry_after_ms = retry_after_ms
        self.run_id = run_id


def ai_not_configured_error() -> ApplicationError:
    return ApplicationError(
        code="AI_NOT_CONFIGURED",
        message="Configure and enable a model connection before using Agent features.",
        status_code=409,
        processing_mode="agent",
    )


def ai_disabled_error() -> ApplicationError:
    return ApplicationError(
        code="AI_DISABLED",
        message="Enable the saved model connection before using Agent features.",
        status_code=409,
        processing_mode="agent",
    )


def credential_store_unavailable_error(
    *,
    processing_mode: ProcessingMode | None = None,
) -> ApplicationError:
    return ApplicationError(
        code="CREDENTIAL_STORE_UNAVAILABLE",
        message="Secure credential storage is temporarily unavailable.",
        status_code=503,
        processing_mode=processing_mode,
    )


def invalid_model_endpoint_error() -> ApplicationError:
    return ApplicationError(
        code="INVALID_MODEL_ENDPOINT",
        message="The custom model endpoint is not allowed by the server security policy.",
        status_code=422,
        processing_mode="agent",
    )


def invalid_upload_file_error() -> ApplicationError:
    return ApplicationError(
        code="INVALID_UPLOAD_FILE",
        message="Only CSV files are supported.",
        status_code=422,
        processing_mode="deterministic",
    )


def account_export_failed_error() -> ApplicationError:
    return ApplicationError(
        code="ACCOUNT_EXPORT_FAILED",
        message="Account data could not be exported. Please try again.",
        status_code=500,
        processing_mode="deterministic",
    )


def account_delete_failed_error() -> ApplicationError:
    return ApplicationError(
        code="ACCOUNT_DELETE_FAILED",
        message="Account could not be deleted. Please try again.",
        status_code=500,
        processing_mode="deterministic",
    )


def model_gateway_error(error: Exception) -> ApplicationError:
    error_name = type(error).__name__.lower()
    provider_status = getattr(error, "status_code", None)
    provider_code = str(getattr(error, "code", "") or "").lower()
    if provider_status in (408, 504) or isinstance(error, TimeoutError) or "timeout" in error_name:
        code = "MODEL_TIMEOUT"
        message = "The model did not respond before the request timed out."
        status_code = 504
        retryable = True
    elif provider_status in (401, 403) or "authentication" in error_name or "permission" in error_name:
        code = "MODEL_AUTH_FAILED"
        message = "The model provider rejected the configured credentials."
        status_code = 502
        retryable = False
    elif provider_code == "model_not_found" or (provider_status == 404 and "model" in provider_code) or error_name == "notfounderror":
        code = "MODEL_NOT_FOUND"
        message = "The configured model could not be found."
        status_code = 422
        retryable = False
    elif provider_status == 429 or "ratelimit" in error_name:
        code = "MODEL_RATE_LIMITED"
        message = "The model provider rate limit was reached."
        status_code = 429
        retryable = True
    else:
        code = "MODEL_PROTOCOL_ERROR"
        message = "The model provider returned an invalid or unsupported response."
        status_code = 502
        retryable = False
    retry_after = getattr(error, "retry_after", None)
    retry_after_ms = int(float(retry_after) * 1000) if isinstance(retry_after, (int, float)) else None
    return ApplicationError(
        code=code,
        message=message,
        status_code=status_code,
        processing_mode="agent",
        retryable=retryable,
        retry_after_ms=retry_after_ms,
    )
