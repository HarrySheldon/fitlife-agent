from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from backend.config import get_settings
from backend.schemas import AuthenticatedUser


PASSWORD_ITERATIONS = 120_000
TOKEN_TTL_HOURS = 24 * 14


def register_user(
    username: str | None,
    email: str | None,
    phone: str | None,
    password: str,
    display_name: str,
) -> AuthenticatedUser:
    users = _read_users()
    normalized_username = normalize_username(username) if username else None
    normalized_email = normalize_email(email) if email else None
    normalized_phone = normalize_phone(phone) if phone else None
    _ensure_unique_identifier(users, "username", normalized_username, "Username")
    _ensure_unique_identifier(users, "email", normalized_email, "Email")
    _ensure_unique_identifier(users, "phone", normalized_phone, "Phone")

    user = {
        "user_id": uuid4().hex,
        "username": normalized_username,
        "email": normalized_email,
        "phone": normalized_phone,
        "display_name": display_name.strip(),
        "password_hash": hash_password(password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    users.append(user)
    _write_users(users)
    return _public_user(user)


def authenticate_user(identifier: str, password: str) -> AuthenticatedUser | None:
    for user in _read_users():
        if _matches_identifier(user, identifier) and verify_password(password, user["password_hash"]):
            return _public_user(user)
    return None


def create_access_token(user: AuthenticatedUser) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)
    payload = {
        "sub": user.user_id,
        "username": user.username,
        "email": user.email,
        "phone": user.phone,
        "display_name": user.display_name,
        "exp": int(expires_at.timestamp()),
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
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
        return None

    user_id = payload.get("sub")
    for user in _read_users():
        if user["user_id"] == user_id:
            return _public_user(user)
    return None


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_username(username: str | None) -> str:
    return (username or "").strip().lower()


def normalize_phone(phone: str | None) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("86") and len(digits) == 13:
        return digits[2:]
    return digits


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        _b64encode(salt),
        _b64encode(digest),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False

    iterations = int(iterations_raw)
    salt = _b64decode(salt_raw)
    expected = _b64decode(digest_raw)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _read_users() -> list[dict]:
    path = _users_path()
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _write_users(users: list[dict]) -> None:
    path = _users_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")


def _users_path() -> Path:
    return get_settings().data_dir / "users.json"


def _public_user(user: dict) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user["user_id"],
        username=user.get("username"),
        email=user.get("email"),
        phone=user.get("phone"),
        display_name=user["display_name"],
    )


def _ensure_unique_identifier(users: list[dict], field: str, value: str | None, label: str) -> None:
    if not value:
        return
    if any(user.get(field) == value for user in users):
        raise ValueError(f"{label} already registered")


def _matches_identifier(user: dict, identifier: str) -> bool:
    normalized_email = normalize_email(identifier)
    normalized_username = normalize_username(identifier)
    normalized_phone = normalize_phone(identifier)
    return any(
        [
            bool(user.get("email") and user.get("email") == normalized_email),
            bool(user.get("username") and user.get("username") == normalized_username),
            bool(user.get("phone") and user.get("phone") == normalized_phone),
        ]
    )


def _sign(payload_part: str) -> str:
    secret = get_settings().auth_secret.encode("utf-8")
    digest = hmac.new(secret, payload_part.encode("utf-8"), hashlib.sha256).digest()
    return _b64encode(digest)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)
