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
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.processing_mode = processing_mode
        self.message_key = message_key or code


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
        message="Secure credential storage is unavailable. Configure SETTINGS_ENCRYPTION_KEY.",
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


def model_gateway_error(error: Exception) -> ApplicationError:
    error_name = type(error).__name__.lower()
    if isinstance(error, TimeoutError) or "timeout" in error_name:
        code = "MODEL_TIMEOUT"
        message = "The model did not respond before the request timed out."
        status_code = 504
    elif "authentication" in error_name or "permission" in error_name:
        code = "MODEL_AUTH_FAILED"
        message = "The model provider rejected the configured credentials."
        status_code = 502
    elif "notfound" in error_name:
        code = "MODEL_NOT_FOUND"
        message = "The configured model could not be found."
        status_code = 422
    elif "ratelimit" in error_name:
        code = "MODEL_RATE_LIMITED"
        message = "The model provider rate limit was reached."
        status_code = 429
    else:
        code = "MODEL_PROTOCOL_ERROR"
        message = "The model provider returned an invalid or unsupported response."
        status_code = 502
    return ApplicationError(
        code=code,
        message=message,
        status_code=status_code,
        processing_mode="agent",
    )
