from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.application.ports.identity_repository import PasswordChangeResult
from backend.schemas import AuthenticatedUser


PASSWORD_ITERATIONS = 120_000
MIN_PASSWORD_ITERATIONS = 100_000
MAX_PASSWORD_ITERATIONS = 1_000_000
MAX_PASSWORD_HASH_LENGTH = 512
MAX_PASSWORD_SALT_BYTES = 64
PASSWORD_DIGEST_BYTES = hashlib.sha256().digest_size

_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class FileIdentityRepository:
    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "users.json"

    def register(
        self,
        username: str | None,
        email: str | None,
        phone: str | None,
        password: str,
        display_name: str,
    ) -> AuthenticatedUser:
        normalized_username = normalize_username(username) if username else None
        normalized_email = normalize_email(email) if email else None
        normalized_phone = normalize_phone(phone) if phone else None

        with _lock_for(self.path):
            users = self._read_users_unlocked()
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
                "token_version": 0,
            }
            users.append(user)
            self._write_users_unlocked(users)

        return _public_user(user)

    def authenticate(self, identifier: str, password: str) -> AuthenticatedUser | None:
        with _lock_for(self.path):
            users = self._read_users_unlocked()
            for user in users:
                if _matches_identifier(user, identifier) and verify_password(password, user["password_hash"]):
                    return _public_user(user)
        return None

    def get_by_id(self, user_id: str) -> AuthenticatedUser | None:
        with _lock_for(self.path):
            user = _find_user(self._read_users_unlocked(), user_id)
            return _public_user(user) if user is not None else None

    def verify_user_password(self, user_id: str, password: str) -> bool:
        with _lock_for(self.path):
            user = _find_user(self._read_users_unlocked(), user_id)
            return bool(user and verify_password(password, user["password_hash"]))

    def replace_password(self, user_id: str, password: str) -> bool:
        password_hash = hash_password(password)
        with _lock_for(self.path):
            users = self._read_users_unlocked()
            user = _find_user(users, user_id)
            if user is None:
                return False
            user["password_hash"] = password_hash
            self._write_users_unlocked(users)
        return True

    def change_password_and_rotate_version(
        self,
        user_id: str,
        expected_token_version: int,
        current_password: str,
        new_password: str,
    ) -> PasswordChangeResult:
        password_hash = hash_password(new_password) if current_password != new_password else None
        with _lock_for(self.path):
            users = self._read_users_unlocked()
            user = _find_user(users, user_id)
            if user is None or int(user.get("token_version", 0)) != expected_token_version:
                return PasswordChangeResult(status="token_invalid")
            if not verify_password(current_password, user["password_hash"]):
                return PasswordChangeResult(status="current_password_invalid")
            if current_password == new_password:
                return PasswordChangeResult(status="password_unchanged")
            assert password_hash is not None
            token_version = expected_token_version + 1
            user["password_hash"] = password_hash
            user["token_version"] = token_version
            self._write_users_unlocked(users)
        return PasswordChangeResult(status="changed", token_version=token_version)

    def get_token_version(self, user_id: str) -> int | None:
        with _lock_for(self.path):
            users = self._read_users_unlocked()
            for user in users:
                if user["user_id"] != user_id:
                    continue
                if "token_version" not in user:
                    user["token_version"] = 0
                    self._write_users_unlocked(users)
                return int(user["token_version"])
        return None

    def rotate_token_version(
        self,
        user_id: str,
        expected_token_version: int | None = None,
    ) -> int | None:
        with _lock_for(self.path):
            users = self._read_users_unlocked()
            user = _find_user(users, user_id)
            if user is None:
                return None
            current_version = int(user.get("token_version", 0))
            if expected_token_version is not None and current_version != expected_token_version:
                return None
            token_version = current_version + 1
            user["token_version"] = token_version
            self._write_users_unlocked(users)
        return token_version

    def validate_token_version(self, user_id: str, token_version: int) -> AuthenticatedUser | None:
        with _lock_for(self.path):
            users = self._read_users_unlocked()
            user = _find_user(users, user_id)
            if user is None:
                return None
            current_version = int(user.get("token_version", 0))
            if "token_version" not in user:
                user["token_version"] = current_version
                self._write_users_unlocked(users)
            return _public_user(user) if current_version == token_version else None

    def delete_identity(self, user_id: str) -> bool:
        with _lock_for(self.path):
            users = self._read_users_unlocked()
            retained = [user for user in users if user["user_id"] != user_id]
            if len(retained) == len(users):
                return False
            self._write_users_unlocked(retained)
        return True

    def _read_users_unlocked(self) -> list[dict]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write_users_unlocked(self, users: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.{uuid4().hex}.tmp")
        payload = json.dumps(users, ensure_ascii=False, indent=2)
        try:
            temporary.write_text(payload, encoding="utf-8")
            self.replace_file(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def replace_file(self, source: Path, destination: Path) -> None:
        os.replace(source, destination)


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
    if not isinstance(password_hash, str) or len(password_hash) > MAX_PASSWORD_HASH_LENGTH:
        return False
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
        if not iterations_raw.isascii() or not iterations_raw.isdecimal():
            return False
        iterations = int(iterations_raw)
        if not MIN_PASSWORD_ITERATIONS <= iterations <= MAX_PASSWORD_ITERATIONS:
            return False
        salt = _decode_hash_field(salt_raw, MAX_PASSWORD_SALT_BYTES)
        expected = _decode_hash_field(digest_raw, PASSWORD_DIGEST_BYTES)
    except (binascii.Error, UnicodeEncodeError, ValueError):
        return False
    if algorithm != "pbkdf2_sha256" or not salt or len(expected) != PASSWORD_DIGEST_BYTES:
        return False

    try:
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    except (OverflowError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def _public_user(user: dict) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user["user_id"],
        username=user.get("username"),
        email=user.get("email"),
        phone=user.get("phone"),
        display_name=user["display_name"],
    )


def _ensure_unique_identifier(users: list[dict], field: str, value: str | None, label: str) -> None:
    if value and any(user.get(field) == value for user in users):
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


def _find_user(users: list[dict], user_id: str) -> dict | None:
    return next((user for user in users if user["user_id"] == user_id), None)


def _lock_for(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(resolved, threading.Lock())


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _decode_hash_field(data: str, max_decoded_bytes: int) -> bytes:
    max_encoded_length = ((max_decoded_bytes + 2) // 3) * 4
    if not data or len(data) > max_encoded_length:
        raise ValueError("Invalid password hash field length")
    padding = "=" * (-len(data) % 4)
    decoded = base64.b64decode((data + padding).encode("ascii"), altchars=b"-_", validate=True)
    if len(decoded) > max_decoded_bytes:
        raise ValueError("Invalid password hash field length")
    return decoded
