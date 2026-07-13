from __future__ import annotations

from backend.domain.errors import ApplicationError
from backend.schemas import ApiError, ApiResponse, ProcessingMode


def ok(
    data=None,
    message: str = "",
    processing_mode: ProcessingMode | None = None,
) -> dict:
    response = ApiResponse(
        success=True,
        data=data,
        message=message,
        processing_mode=processing_mode,
    )
    return _dump_response(response)


def fail(
    message: str,
    processing_mode: ProcessingMode | None = None,
) -> dict:
    return _dump_response(
        ApiResponse(
            success=False,
            data=None,
            message=message,
            processing_mode=processing_mode,
        )
    )


def application_error_response(error: ApplicationError) -> dict:
    response = ApiResponse(
        success=False,
        data=None,
        message=error.message,
        processing_mode=error.processing_mode,
        error=ApiError(code=error.code, message=error.message),
    )
    return _dump_response(response)


def _dump_response(response: ApiResponse) -> dict:
    exclude = set()
    if response.processing_mode is None:
        exclude.add("processing_mode")
    if response.error is None:
        exclude.add("error")
    return response.model_dump(exclude=exclude)
