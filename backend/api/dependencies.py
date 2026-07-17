from __future__ import annotations

from fastapi import Header, Request

from backend.domain.errors import ApplicationError
from backend.schemas import AuthenticatedPrincipal, AuthenticatedUser
from backend.tools.auth_store import principal_from_token, user_from_token


def optional_current_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser | None:
    if authorization is None:
        return None
    token = _bearer_token(authorization)
    if token is None:
        raise _invalid_token_error()
    user = user_from_token(token)
    if user is None:
        raise _invalid_token_error()
    return user


def require_current_user(request: Request, authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    return _require_principal(authorization).user


def require_current_principal(
    request: Request,
    authorization: str | None = Header(default=None),
) -> AuthenticatedPrincipal:
    return _require_principal(authorization)


def _require_principal(authorization: str | None) -> AuthenticatedPrincipal:
    if authorization is None:
        raise ApplicationError(code="AUTH_REQUIRED", message="Authentication is required.", status_code=401)
    token = _bearer_token(authorization)
    if token is None:
        raise _invalid_token_error()
    principal = principal_from_token(token)
    if principal is None:
        raise _invalid_token_error()
    return principal


def _invalid_token_error() -> ApplicationError:
    return ApplicationError(
        code="AUTH_TOKEN_INVALID",
        message="The session is invalid or has expired.",
        status_code=401,
    )


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token
