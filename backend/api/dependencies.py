from __future__ import annotations

from fastapi import Header, HTTPException

from backend.schemas import AuthenticatedUser
from backend.tools.auth_store import user_from_token


def optional_current_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser | None:
    token = _bearer_token(authorization)
    if token is None:
        return None
    return user_from_token(token)


def require_current_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    token = _bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    user = user_from_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired bearer token")
    return user


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token
