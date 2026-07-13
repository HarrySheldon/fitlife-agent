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
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.processing_mode = processing_mode


def ai_not_configured_error() -> ApplicationError:
    return ApplicationError(
        code="AI_NOT_CONFIGURED",
        message="Configure and enable a model connection before using Agent features.",
        status_code=409,
        processing_mode="agent",
    )
