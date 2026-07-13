from __future__ import annotations

from backend.domain.errors import ApplicationError
from backend.schemas import ApiError, ApiResponse, ProcessingMode


def ok(
    data=None,
    message: str = "",
    processing_mode: ProcessingMode | None = None,
) -> dict:
    return ApiResponse(
        success=True,
        data=data,
        message=message,
        processing_mode=processing_mode,
    ).model_dump()


def fail(message: str) -> dict:
    return ApiResponse(success=False, data=None, message=message).model_dump()


def application_error_response(error: ApplicationError) -> dict:
    return ApiResponse(
        success=False,
        data=None,
        message=error.message,
        processing_mode=error.processing_mode,
        error=ApiError(code=error.code, message=error.message),
    ).model_dump()
