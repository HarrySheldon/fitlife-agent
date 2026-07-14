from __future__ import annotations

from fastapi import Header, Request

from backend.domain.errors import ApplicationError
from backend.schemas import AuthenticatedUser
from backend.tools.auth_store import user_from_token


def optional_current_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser | None:
    token = _bearer_token(authorization)
    if token is None:
        return None
    return user_from_token(token)


def require_current_user(request: Request, authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    token = _bearer_token(authorization)
    if token is None:
        raise ApplicationError(code="AUTH_REQUIRED", message="Authentication is required.", status_code=401)
    user = user_from_token(token)
    if user is None:
        raise ApplicationError(
            code="AUTH_TOKEN_INVALID",
            message="The session is invalid or has expired.",
            status_code=401,
        )
    return user


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token
