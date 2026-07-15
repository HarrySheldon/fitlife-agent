from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, Sequence
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from backend.application.ports.identity_repository import IdentityExportMetadata, IdentityRepository
from backend.application.ports.model_connection_repository import ModelConnectionRepository


_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
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


@dataclass(frozen=True)
class AccountExportEntry:
    archive_path: str
    content: bytes


class AccountExportSource(Protocol):
    def export_entries(self, user_id: str) -> Sequence[AccountExportEntry]: ...


class ExportAccountData:
    def __init__(
        self,
        data_dir: Path,
        identities: IdentityRepository,
        model_connections: ModelConnectionRepository | None = None,
        additional_sources: Sequence[AccountExportSource] = (),
    ) -> None:
        self.data_dir = Path(data_dir)
        self.identities = identities
        self.model_connections = model_connections
        self.additional_sources = tuple(additional_sources)

    def execute(self, user_id: str) -> bytes:
        if not _USER_ID_PATTERN.fullmatch(user_id):
            raise ValueError("Invalid user id")
        identity = self.identities.get_export_metadata(user_id)
        if identity is None:
            raise ValueError("Identity not found")

        entries = {"identity.json": _stable_json(asdict(identity))}
        user_root = _validated_user_root(self.data_dir, user_id)
        if user_root.exists():
            for archive_path, filename, fields in _FILE_EXPORTS:
                source = _validated_optional_file(user_root, filename)
                if source is not None:
                    entries[archive_path] = _stable_json(
                        _project_fields(json.loads(source.read_text(encoding="utf-8")), fields)
                    )
            for archive_path, filename, fields in _RECORD_EXPORTS:
                source = _validated_optional_file(user_root, filename)
                if source is not None:
                    entries[archive_path] = _stable_csv(source, fields)
            if self.model_connections is not None:
                model_source = _validated_optional_file(user_root, "model_connection.json")
                if model_source is not None:
                    model_connection = self.model_connections.get_public(user_id)
                    if model_connection is not None:
                        entries["model-connection.json"] = _stable_json(
                            _project_fields(
                                model_connection.model_dump(mode="json"),
                                _MODEL_CONNECTION_FIELDS,
                            )
                        )
        for source in self.additional_sources:
            for entry in source.export_entries(user_id):
                archive_path = _validated_archive_path(entry.archive_path, identity)
                if archive_path in entries:
                    raise ValueError(f"Duplicate account export path: {archive_path}")
                entries[archive_path] = bytes(entry.content)
        archive = io.BytesIO()
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as exported:
            for path in sorted(entries):
                info = ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                exported.writestr(info, entries[path])
        return archive.getvalue()


def _stable_json(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _project_fields(payload: dict, fields: tuple[str, ...]) -> dict:
    return {field: payload[field] for field in fields if field in payload}


def _stable_csv(source: Path, fields: tuple[str, ...]) -> bytes:
    reader = csv.DictReader(io.StringIO(source.read_text(encoding="utf-8"), newline=""))
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in reader:
        writer.writerow({field: row.get(field, "") for field in fields})
    return output.getvalue().encode("utf-8")


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


def _validated_optional_file(user_root: Path, filename: str) -> Path | None:
    source = user_root / filename
    if source.is_symlink():
        raise ValueError("Symbolic links are not allowed in account exports")
    if not source.exists():
        return None
    if not source.is_file() or not source.resolve().is_relative_to(user_root.resolve()):
        raise ValueError("Export source must be a regular file under the user root")
    return source


def _validated_archive_path(path: str, identity: IdentityExportMetadata) -> str:
    archive_path = PurePosixPath(path)
    if (
        not path
        or "\\" in path
        or archive_path.is_absolute()
        or str(archive_path) != path
        or any(part in {"", ".", ".."} for part in archive_path.parts)
    ):
        raise ValueError("Account export paths must be safe relative POSIX paths")
    identifiers = {
        value
        for value in (identity.user_id, identity.username, identity.email, identity.phone)
        if value
    }
    if any(part in identifiers for part in archive_path.parts):
        raise ValueError("Account export paths cannot contain account identifiers")
    return path
