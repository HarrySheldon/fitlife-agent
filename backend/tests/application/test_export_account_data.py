from __future__ import annotations

import csv
import io
import inspect
import json
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import pytest

import backend.application.use_cases.export_account_data as export_module
from backend.application.use_cases.export_account_data import ExportAccountData
from backend.domain.errors import ApplicationError
from backend.domain.model_connection import ModelConnection
from backend.infrastructure.auth.file_identity_repository import FileIdentityRepository
from backend.infrastructure.settings.file_model_connection_repository import FileModelConnectionRepository


def make_data_dir() -> Path:
    return Path(".tmp") / "pytest-account-export" / uuid4().hex


def assert_export_failed(error: ApplicationError) -> None:
    assert error.code == "ACCOUNT_EXPORT_FAILED"
    assert error.message == "Account data could not be exported. Please try again."


def test_export_contains_only_allowlisted_identity_metadata_as_stable_json():
    data_dir = make_data_dir()
    identities = FileIdentityRepository(data_dir)
    user = identities.register(
        username="export-user",
        email="export@example.com",
        phone="13800138000",
        password="password123",
        display_name="导出用户",
    )

    archive = ExportAccountData(data_dir, identities).execute(user.user_id)

    with ZipFile(io.BytesIO(archive)) as exported:
        assert exported.namelist() == ["identity.json"]
        payload = exported.read("identity.json")
    identity = json.loads(payload)
    assert set(identity) == {
        "user_id",
        "username",
        "email",
        "phone",
        "display_name",
        "created_at",
    }
    assert identity["user_id"] == user.user_id
    assert identity["display_name"] == "导出用户"
    assert payload == (
        json.dumps(identity, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    assert list(data_dir.rglob("*.zip")) == []


def test_export_constructor_does_not_accept_additional_sources():
    data_dir = make_data_dir()
    identities = FileIdentityRepository(data_dir)

    assert "additional_sources" not in inspect.signature(ExportAccountData).parameters
    with pytest.raises(TypeError, match="additional_sources"):
        ExportAccountData(data_dir, identities, additional_sources=())


def test_export_rejects_a_source_larger_than_the_explicit_limit(monkeypatch):
    data_dir = make_data_dir()
    identities = FileIdentityRepository(data_dir)
    user = identities.register("oversized-source", None, None, "password123", "Oversized")
    user_root = data_dir / "users" / user.user_id
    user_root.mkdir(parents=True)
    monkeypatch.setattr(export_module, "MAX_SOURCE_BYTES", 1024, raising=False)
    (user_root / "user_profile.json").write_text(
        json.dumps({"display_padding": "x" * 2048}), encoding="utf-8"
    )

    with pytest.raises(ApplicationError) as raised:
        ExportAccountData(data_dir, identities).execute(user.user_id)

    assert_export_failed(raised.value)
    assert "user_profile" not in raised.value.message


def test_export_rejects_sources_that_exceed_the_aggregate_limit(monkeypatch):
    data_dir = make_data_dir()
    identities = FileIdentityRepository(data_dir)
    user = identities.register("aggregate-limit", None, None, "password123", "Aggregate")
    user_root = data_dir / "users" / user.user_id
    user_root.mkdir(parents=True)
    meals = (
        "date,meal,food,amount,calories,protein,carbs,fat\n"
        f"2026-07-15,lunch,{'m' * 300},1,1,1,1,1\n"
    ).encode()
    workouts = (
        "date,type,exercise,muscle_group,sets,reps,weight,duration_min\n"
        f"2026-07-15,strength,{'w' * 300},legs,1,1,1,1\n"
    ).encode()
    (user_root / "meals.csv").write_bytes(meals)
    (user_root / "workouts.csv").write_bytes(workouts)
    identity_size = (data_dir / "users.json").stat().st_size
    monkeypatch.setattr(export_module, "MAX_SOURCE_BYTES", 4096)
    monkeypatch.setattr(
        export_module,
        "MAX_EXPORT_BYTES",
        identity_size + len(meals) + len(workouts) - 1,
    )

    with pytest.raises(ApplicationError) as raised:
        ExportAccountData(data_dir, identities).execute(user.user_id)

    assert_export_failed(raised.value)


@pytest.mark.parametrize(
    ("filename", "content", "include_models"),
    [
        ("user_profile.json", b"\xff", False),
        ("user_profile.json", b"{", False),
        ("user_profile.json", b"[]", False),
        ("model_connection.json", b'{"provider":"invalid"}', True),
        (
            "meals.csv",
            b'date,meal,food,amount,calories,protein,carbs,fat\n'
            b'2026-07-15,lunch,"unterminated',
            False,
        ),
    ],
)
def test_export_sanitizes_malformed_source_failures(filename, content, include_models):
    data_dir = make_data_dir()
    identities = FileIdentityRepository(data_dir)
    user = identities.register("malformed-export", None, None, "password123", "Malformed")
    source = data_dir / "users" / user.user_id / filename
    source.parent.mkdir(parents=True)
    source.write_bytes(content)
    models = FileModelConnectionRepository(data_dir) if include_models else None

    with pytest.raises(ApplicationError) as raised:
        ExportAccountData(data_dir, identities, models).execute(user.user_id)

    assert_export_failed(raised.value)
    assert filename not in raised.value.message
    assert "JSON" not in raised.value.message
    assert "UTF" not in raised.value.message
    assert "CSV" not in raised.value.message


@pytest.mark.parametrize("dangerous_prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_export_escapes_csv_cells_that_spreadsheet_apps_can_execute(dangerous_prefix):
    data_dir = make_data_dir()
    identities = FileIdentityRepository(data_dir)
    user = identities.register("csv-injection", None, None, "password123", "CSV")
    user_root = data_dir / "users" / user.user_id
    user_root.mkdir(parents=True)
    dangerous_cell = f"{dangerous_prefix}cmd|' /C calc'!A0"
    source = io.StringIO(newline="")
    writer = csv.writer(source, lineterminator="\n")
    writer.writerow(("date", "meal", "food", "amount", "calories", "protein", "carbs", "fat"))
    writer.writerow(("2026-07-15", "lunch", dangerous_cell, "1", "1", "1", "1", "1"))
    (user_root / "meals.csv").write_text(
        source.getvalue(),
        encoding="utf-8",
    )

    archive = ExportAccountData(data_dir, identities).execute(user.user_id)

    with ZipFile(io.BytesIO(archive)) as exported:
        rows = list(
            csv.DictReader(
                io.StringIO(exported.read("records/meals.csv").decode("utf-8"))
            )
        )
    assert rows[0]["food"] == f"'{dangerous_cell}"


def test_export_includes_only_fixed_user_sources_and_sanitized_fields():
    data_dir = make_data_dir()
    identities = FileIdentityRepository(data_dir)
    current = identities.register("current", None, None, "password123", "当前用户")
    other = identities.register("other", None, None, "password456", "其他用户")
    current_root = data_dir / "users" / current.user_id
    other_root = data_dir / "users" / other.user_id
    current_root.mkdir(parents=True)
    other_root.mkdir(parents=True)
    profile = {
        "height_cm": 175,
        "weight_kg": 72,
        "age": 24,
        "gender": "other",
        "goal": "maintenance",
        "weekly_training_frequency": 4,
        "diet_preferences": ["高蛋白"],
        "allergies_or_restrictions": [],
        "target_weight_kg": 70,
        "daily_calorie_target": 2200,
        "daily_protein_target": 130,
        "experience_level": "novice",
        "training_preference": "mixed",
        "target_mode": "suggested",
        "auth_secret": "do-not-export",
    }
    preferences = {
        "language": "zh-CN",
        "unit_system": "metric",
        "timezone": "Asia/Shanghai",
        "auth_secret": "do-not-export",
    }
    (current_root / "user_profile.json").write_text(
        json.dumps(profile, ensure_ascii=False), encoding="utf-8"
    )
    (current_root / "preferences.json").write_text(
        json.dumps(preferences, ensure_ascii=False), encoding="utf-8"
    )
    meals = "date,meal,food,amount,calories,protein,carbs,fat\n2026-07-15,lunch,鸡胸肉,200g,330,62,0,7\n"
    stored_meals = "date,meal,food,amount,calories,protein,carbs,fat,auth_secret\n2026-07-15,lunch,鸡胸肉,200g,330,62,0,7,csv-secret\n"
    workouts = "date,type,exercise,muscle_group,sets,reps,weight,duration_min\n2026-07-15,strength,深蹲,legs,4,8,80,45\n"
    (current_root / "meals.csv").write_bytes(stored_meals.encode("utf-8"))
    (current_root / "workouts.csv").write_bytes(workouts.encode("utf-8"))
    (current_root / "rogue.json").write_text('{"leak": true}', encoding="utf-8")
    (current_root / "notes.tmp").write_text("temporary secret", encoding="utf-8")
    (other_root / "meals.csv").write_text("other-user-secret", encoding="utf-8")
    models = FileModelConnectionRepository(data_dir)
    models.save(
        current.user_id,
        ModelConnection(
            provider="custom",
            protocol="chat_completions",
            base_url="https://模型.example/v1",
            model="私有模型",
            encrypted_api_key="encrypted-secret",
            api_key_hint="********cret",
            enabled=True,
            test_status="success",
        ),
    )

    archive = ExportAccountData(data_dir, identities, models).execute(current.user_id)

    with ZipFile(io.BytesIO(archive)) as exported:
        assert exported.namelist() == [
            "identity.json",
            "model-connection.json",
            "preferences.json",
            "profile.json",
            "records/meals.csv",
            "records/workouts.csv",
        ]
        contents = {name: exported.read(name) for name in exported.namelist()}
    assert contents["records/meals.csv"] == meals.encode("utf-8")
    assert contents["records/workouts.csv"] == workouts.encode("utf-8")
    assert json.loads(contents["profile.json"]) == {
        key: value for key, value in profile.items() if key != "auth_secret"
    }
    assert json.loads(contents["preferences.json"]) == {
        key: value for key, value in preferences.items() if key != "auth_secret"
    }
    model = json.loads(contents["model-connection.json"])
    assert model["api_key_configured"] is True
    assert "api_key_hint" not in model
    combined = b"\n".join(contents.values())
    for forbidden in (
        b"password_hash",
        b"token_version",
        b"auth_secret",
        b"csv-secret",
        b"encrypted-secret",
        b"api_key_hint",
        b"other-user-secret",
        b"temporary secret",
        b"rogue",
    ):
        assert forbidden not in combined
    for name in ("profile.json", "preferences.json", "model-connection.json"):
        decoded = json.loads(contents[name])
        assert contents[name] == (
            json.dumps(decoded, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")


def test_export_rejects_a_symlinked_user_root(monkeypatch):
    data_dir = make_data_dir()
    identities = FileIdentityRepository(data_dir)
    user = identities.register("linked-root", None, None, "password123", "Linked")
    user_root = data_dir / "users" / user.user_id
    user_root.mkdir(parents=True)
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == user_root or original_is_symlink(path),
    )

    with pytest.raises(ApplicationError) as raised:
        ExportAccountData(data_dir, identities).execute(user.user_id)

    assert_export_failed(raised.value)


def test_export_rejects_an_included_file_symlink(monkeypatch):
    data_dir = make_data_dir()
    identities = FileIdentityRepository(data_dir)
    user = identities.register("linked-file", None, None, "password123", "Linked")
    meals_path = data_dir / "users" / user.user_id / "meals.csv"
    meals_path.parent.mkdir(parents=True)
    meals_path.write_text("must-not-export", encoding="utf-8")
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == meals_path or original_is_symlink(path),
    )

    with pytest.raises(ApplicationError) as raised:
        ExportAccountData(data_dir, identities).execute(user.user_id)

    assert_export_failed(raised.value)


def test_export_rejects_a_symlinked_identity_source(monkeypatch):
    data_dir = make_data_dir()
    identities = FileIdentityRepository(data_dir)
    user = identities.register("linked-identity", None, None, "password123", "Linked")
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == identities.path or original_is_symlink(path),
    )

    with pytest.raises(ApplicationError) as raised:
        ExportAccountData(data_dir, identities).execute(user.user_id)

    assert_export_failed(raised.value)


def test_export_validates_opened_snapshot_before_reading_changed_content(monkeypatch):
    data_dir = make_data_dir()
    identities = FileIdentityRepository(data_dir)
    user = identities.register("changed-source", None, None, "password123", "Changed")
    source = data_dir / "users" / user.user_id / "user_profile.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"height_cm":170}', encoding="utf-8")
    real_open = export_module.os.open
    real_read = export_module.os.read
    target_descriptor = None
    source_was_read = False

    def change_before_open(path, flags):
        nonlocal target_descriptor
        if Path(path) == source:
            source.write_text('{"height_cm":170,"weight_kg":70}', encoding="utf-8")
        descriptor = real_open(path, flags)
        if Path(path) == source:
            target_descriptor = descriptor
        return descriptor

    def observe_read(descriptor, size):
        nonlocal source_was_read
        if descriptor == target_descriptor:
            source_was_read = True
        return real_read(descriptor, size)

    monkeypatch.setattr(export_module.os, "open", change_before_open)
    monkeypatch.setattr(export_module.os, "read", observe_read)

    with pytest.raises(ApplicationError) as raised:
        ExportAccountData(data_dir, identities).execute(user.user_id)

    assert_export_failed(raised.value)
    assert source_was_read is False


@pytest.mark.parametrize("user_id", ["../other", "user/other", "user\\other", ""])
def test_export_rejects_user_id_path_traversal(user_id: str):
    data_dir = make_data_dir()

    with pytest.raises(ApplicationError) as raised:
        ExportAccountData(data_dir, FileIdentityRepository(data_dir)).execute(user_id)

    assert_export_failed(raised.value)
