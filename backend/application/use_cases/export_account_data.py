from __future__ import annotations

import csv
import io
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from backend.application.ports.identity_repository import IdentityRepository
from backend.application.ports.model_connection_repository import ModelConnectionRepository
from backend.domain.errors import account_export_failed_error


_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MAX_SOURCE_BYTES = 5 * 1024 * 1024
MAX_EXPORT_BYTES = 20 * 1024 * 1024
_PROFILE_FIELDS = (
    "height_cm",
    "weight_kg",
    "age",
    "gender",
    "goal",
    "weekly_training_frequency",
    "diet_preferences",
    "allergies_or_restrictions",
    "target_weight_kg",
    "daily_calorie_target",
    "daily_protein_target",
    "experience_level",
    "training_preference",
    "target_mode",
)
_PREFERENCE_FIELDS = ("language", "unit_system", "timezone")
_MODEL_CONNECTION_FIELDS = (
    "provider",
    "protocol",
    "base_url",
    "model",
    "enabled",
    "api_key_configured",
    "test_status",
    "test_error_code",
    "tested_at",
    "updated_at",
    "state",
)
_FILE_EXPORTS = (
    ("preferences.json", "preferences.json", _PREFERENCE_FIELDS),
    ("profile.json", "user_profile.json", _PROFILE_FIELDS),
)
_RECORD_EXPORTS = (
    (
        "records/meals.csv",
        "meals.csv",
        ("date", "meal", "food", "amount", "calories", "protein", "carbs", "fat"),
    ),
    (
        "records/workouts.csv",
        "workouts.csv",
        ("date", "type", "exercise", "muscle_group", "sets", "reps", "weight", "duration_min"),
    ),
)


@dataclass
class _ExportBudget:
    source_bytes: int = 0
    entry_bytes: int = 0

    def read_snapshot(
        self,
        root: Path,
        filename: str,
        *,
        boundary: Path | None = None,
    ) -> bytes | None:
        remaining = MAX_EXPORT_BYTES - self.source_bytes
        snapshot = _safe_read_snapshot(
            root,
            filename,
            boundary=boundary,
            max_bytes=min(MAX_SOURCE_BYTES, max(0, remaining)),
        )
        if snapshot is not None:
            self.source_bytes += len(snapshot)
        return snapshot

    def add_entry(self, entries: dict[str, bytes], path: str, content: bytes) -> None:
        self.entry_bytes += len(content)
        if self.entry_bytes > MAX_EXPORT_BYTES:
            raise ValueError("Account export entries exceed the size limit")
        entries[path] = content


class ExportAccountData:
    def __init__(
        self,
        data_dir: Path,
        identities: IdentityRepository,
        model_connections: ModelConnectionRepository | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.identities = identities
        self.model_connections = model_connections

    def execute(self, user_id: str) -> bytes:
        try:
            return self._execute(user_id)
        except Exception:
            raise account_export_failed_error() from None

    def _execute(self, user_id: str) -> bytes:
        if not _USER_ID_PATTERN.fullmatch(user_id):
            raise ValueError("Invalid user id")
        budget = _ExportBudget()
        identity_snapshot = budget.read_snapshot(self.data_dir, "users.json")
        if identity_snapshot is None:
            raise ValueError("Identity source not found")
        identity = self.identities.project_export_metadata(user_id, identity_snapshot)
        if identity is None:
            raise ValueError("Identity not found")

        entries: dict[str, bytes] = {}
        budget.add_entry(entries, "identity.json", _stable_json(asdict(identity)))
        user_root = _validated_user_root(self.data_dir, user_id)
        if user_root.exists():
            for archive_path, filename, fields in _FILE_EXPORTS:
                snapshot = budget.read_snapshot(
                    user_root,
                    filename,
                    boundary=self.data_dir / "users",
                )
                if snapshot is not None:
                    budget.add_entry(
                        entries,
                        archive_path,
                        _stable_json(_project_fields(_json_object(snapshot), fields)),
                    )
            for archive_path, filename, fields in _RECORD_EXPORTS:
                snapshot = budget.read_snapshot(
                    user_root,
                    filename,
                    boundary=self.data_dir / "users",
                )
                if snapshot is not None:
                    budget.add_entry(entries, archive_path, _stable_csv(snapshot, fields))
            if self.model_connections is not None:
                model_snapshot = budget.read_snapshot(
                    user_root,
                    "model_connection.json",
                    boundary=self.data_dir / "users",
                )
                if model_snapshot is not None:
                    model_connection = self.model_connections.project_public(model_snapshot)
                    budget.add_entry(
                        entries,
                        "model-connection.json",
                        _stable_json(
                            _project_fields(
                                model_connection.model_dump(mode="json"),
                                _MODEL_CONNECTION_FIELDS,
                            )
                        ),
                    )
        archive = io.BytesIO()
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as exported:
            for path in sorted(entries):
                info = ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                exported.writestr(info, entries[path])
        result = archive.getvalue()
        if len(result) > MAX_EXPORT_BYTES:
            raise ValueError("Account export archive exceeds the size limit")
        return result


def _stable_json(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _project_fields(payload: dict, fields: tuple[str, ...]) -> dict:
    return {field: payload[field] for field in fields if field in payload}


def _stable_csv(snapshot: bytes, fields: tuple[str, ...]) -> bytes:
    reader = csv.DictReader(io.StringIO(snapshot.decode("utf-8"), newline=""), strict=True)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in reader:
        writer.writerow({field: _escape_csv_cell(row.get(field)) for field in fields})
    return output.getvalue().encode("utf-8")


def _escape_csv_cell(value: str | None) -> str:
    cell = value or ""
    return f"'{cell}" if cell.startswith(("=", "+", "-", "@", "\t", "\r")) else cell


def _validated_user_root(data_dir: Path, user_id: str) -> Path:
    users_root = data_dir / "users"
    user_root = users_root / user_id
    if users_root.is_symlink() or user_root.is_symlink():
        raise ValueError("Symbolic links are not allowed in account exports")
    resolved_users_root = users_root.resolve(strict=False)
    resolved_user_root = user_root.resolve(strict=False)
    if not resolved_user_root.is_relative_to(resolved_users_root):
        raise ValueError("User data path escapes data/users")
    return user_root


def _json_object(snapshot: bytes) -> dict:
    payload = json.loads(snapshot.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON export source must contain an object")
    return payload


def _safe_read_snapshot(
    root: Path,
    filename: str,
    *,
    boundary: Path | None = None,
    max_bytes: int = MAX_SOURCE_BYTES,
) -> bytes | None:
    root_before = _validated_snapshot_root(root, boundary)
    if root_before is None:
        return None
    source = root / filename
    if source.is_symlink():
        raise ValueError("Symbolic links are not allowed in account exports")
    try:
        path_before = os.lstat(source)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(path_before.st_mode) or path_before.st_size > max_bytes:
        raise ValueError("Invalid account export source")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    try:
        opened = os.fstat(descriptor)
        if not _same_snapshot(path_before, opened):
            raise ValueError("Account export source changed before opening")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, max_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > max_bytes:
                raise ValueError("Account export source exceeds the size limit")
        opened_after = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    path_after = os.lstat(source)
    root_after = _validated_snapshot_root(root, boundary)
    if (
        root_after is None
        or root_before != root_after
        or not _same_snapshot(path_before, opened_after)
        or not _same_snapshot(path_before, path_after)
    ):
        raise ValueError("Account export source changed while reading")
    return b"".join(chunks)


def _validated_snapshot_root(root: Path, boundary: Path | None) -> tuple | None:
    if boundary is not None:
        if boundary.is_symlink():
            raise ValueError("Symbolic links are not allowed in account exports")
        boundary_stat = os.lstat(boundary)
        if not stat.S_ISDIR(boundary_stat.st_mode):
            raise ValueError("Invalid account export root")
        if not root.resolve(strict=False).is_relative_to(boundary.resolve(strict=False)):
            raise ValueError("Account export root escapes its boundary")
    if root.is_symlink():
        raise ValueError("Symbolic links are not allowed in account exports")
    try:
        root_stat = os.lstat(root)
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("Invalid account export root")
    return _snapshot_fingerprint(root_stat)


def _same_snapshot(before: os.stat_result, after: os.stat_result) -> bool:
    return _snapshot_fingerprint(before) == _snapshot_fingerprint(after)


def _snapshot_fingerprint(value: os.stat_result) -> tuple:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_size,
        value.st_mtime_ns,
    )
