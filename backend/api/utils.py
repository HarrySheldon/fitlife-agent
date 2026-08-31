from __future__ import annotations

from backend.domain.errors import ApplicationError
from backend.i18n import translate_public_message
from backend.domain.user_preferences import AppLanguage
from backend.schemas import ApiError, ApiResponse, ProcessingMode
from uuid import uuid4
from fastapi import Request


def request_id_for(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if request_id is None:
        request_id = uuid4().hex
        request.state.request_id = request_id
    return request_id


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


def application_error_response(error: ApplicationError, language: AppLanguage = "en-US", request_id: str = "") -> dict:
    message = translate_public_message(error.message_key, language, error.message)
    response = ApiResponse(
        success=False,
        data=None,
        message=message,
        processing_mode=error.processing_mode,
        error=ApiError(code=error.code, message=message, action=getattr(error, "action", None),
                       retryable=getattr(error, "retryable", False),
                       retry_after_ms=getattr(error, "retry_after_ms", None), request_id=request_id),
    )
    return _dump_response(response)


def _dump_response(response: ApiResponse) -> dict:
    exclude = set()
    if response.processing_mode is None:
        exclude.add("processing_mode")
    if response.error is None:
        exclude.add("error")
    return response.model_dump(exclude=exclude)
