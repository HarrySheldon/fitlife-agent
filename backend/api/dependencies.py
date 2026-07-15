from __future__ import annotations

from fastapi import Header, Request

from backend.domain.errors import ApplicationError
from backend.schemas import AuthenticatedPrincipal, AuthenticatedUser
from backend.tools.auth_store import principal_from_token, user_from_token


def optional_current_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser | None:
    token = _bearer_token(authorization)
    if token is None:
        return None
    return user_from_token(token)


def require_current_user(request: Request, authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    return _require_principal(authorization).user


def require_current_principal(
    request: Request,
    authorization: str | None = Header(default=None),
) -> AuthenticatedPrincipal:
    return _require_principal(authorization)


def _require_principal(authorization: str | None) -> AuthenticatedPrincipal:
    token = _bearer_token(authorization)
    if token is None:
        raise ApplicationError(code="AUTH_REQUIRED", message="Authentication is required.", status_code=401)
    principal = principal_from_token(token)
    if principal is None:
        raise ApplicationError(
            code="AUTH_TOKEN_INVALID",
            message="The session is invalid or has expired.",
            status_code=401,
        )
    return principal


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token
