from __future__ import annotations

from backend.schemas import ApiResponse


def ok(data=None, message: str = "") -> dict:
    return ApiResponse(success=True, data=data, message=message).model_dump()


def fail(message: str) -> dict:
    return ApiResponse(success=False, data=None, message=message).model_dump()
