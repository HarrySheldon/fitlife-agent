from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from backend.config import get_settings
from backend.infrastructure.auth.file_identity_repository import (
    PASSWORD_ITERATIONS,
    FileIdentityRepository,
    hash_password,
    normalize_email,
    normalize_phone,
    normalize_username,
    verify_password,
)
from backend.schemas import AuthTokenClaims, AuthenticatedUser


TOKEN_TTL_HOURS = 24 * 14


def register_user(
    username: str | None,
    email: str | None,
    phone: str | None,
    password: str,
    display_name: str,
) -> AuthenticatedUser:
    return _repository().register(username, email, phone, password, display_name)


def authenticate_user(identifier: str, password: str) -> AuthenticatedUser | None:
    return _repository().authenticate(identifier, password)


def create_access_token(user: AuthenticatedUser) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)
    token_version = _repository().get_token_version(user.user_id)
    payload = {
        "sub": user.user_id,
        "username": user.username,
        "email": user.email,
        "phone": user.phone,
        "display_name": user.display_name,
        "exp": int(expires_at.timestamp()),
        "ver": token_version if token_version is not None else 0,
    }
    payload_part = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _sign(payload_part)
    return f"{payload_part}.{signature}"


def user_from_token(token: str) -> AuthenticatedUser | None:
    try:
        payload_part, signature = token.split(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(_sign(payload_part), signature):
        return None

    try:
        payload = json.loads(_b64decode(payload_part).decode("utf-8"))
        claims = AuthTokenClaims.model_validate(payload)
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, ValueError):
        return None
    if claims.exp <= int(datetime.now(timezone.utc).timestamp()):
        return None

    return _repository().validate_token_version(claims.sub, claims.ver)


def _sign(payload_part: str) -> str:
    secret = get_settings().auth_secret.encode("utf-8")
    digest = hmac.new(secret, payload_part.encode("utf-8"), hashlib.sha256).digest()
    return _b64encode(digest)


def _repository() -> FileIdentityRepository:
    return FileIdentityRepository(get_settings().data_dir)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)
