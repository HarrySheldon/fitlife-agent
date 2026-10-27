"""One source per deployment, and the switch refuses to guess.

The failure these tests are built around is quiet: a deployment that turns on
``sqlite`` before importing serves every user an empty plan history while the
files sit on disk. Nothing errors, nothing logs, and the UI shows "no plans".
So the refusal has to happen at construction time, not on the first read.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.config import Settings
from backend.domain.errors import ApplicationError
from backend.infrastructure.repositories.file_plan_repository import FilePlanRepository
from backend.infrastructure.repositories.plan_repository_factory import (
    build_plan_activation_repository,
    build_plan_repository,
    require_imported,
)
from backend.infrastructure.repositories.sqlite_plan_repository import (
    SQLitePlanRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)


def _settings(tmp_path, mode="file"):
    return Settings(data_dir=tmp_path / "data", plan_storage_mode=mode,
                    sqlite_database_path=None)


def _database(tmp_path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    return database


def _record_import(database, data_dir, *, owners=1, plans=2):
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO plan_import_state (id, data_dir, completed_at, owner_count,"
            " plan_count, draft_count) VALUES (1, ?, ?, ?, ?, 0)"
            " ON CONFLICT(id) DO UPDATE SET data_dir=excluded.data_dir,"
            " owner_count=excluded.owner_count, plan_count=excluded.plan_count",
            (str(data_dir.resolve()), NOW.isoformat(), owners, plans))


def test_the_default_mode_is_the_file_store(tmp_path):
    repository = build_plan_repository(_settings(tmp_path))

    assert isinstance(repository, FilePlanRepository)


def test_file_mode_never_opens_the_database(tmp_path):
    settings = _settings(tmp_path)
    build_plan_repository(settings)

    assert not settings.database_path.exists()


def test_sqlite_mode_without_an_import_is_refused(tmp_path):
    with pytest.raises(ApplicationError) as raised:
        build_plan_repository(_settings(tmp_path, "sqlite"), database=_database(tmp_path))

    assert raised.value.code == "CONFIGURATION_INVALID"
    assert "import" in raised.value.message


def test_an_import_of_a_different_directory_is_refused(tmp_path):
    database = _database(tmp_path)
    _record_import(database, tmp_path / "somewhere-else")

    with pytest.raises(ApplicationError) as raised:
        build_plan_repository(_settings(tmp_path, "sqlite"), database=database)

    assert raised.value.code == "CONFIGURATION_INVALID"


def test_sqlite_mode_with_a_matching_import_returns_the_sqlite_store(tmp_path):
    database = _database(tmp_path)
    settings = _settings(tmp_path, "sqlite")
    _record_import(database, settings.data_dir)

    repository = build_plan_repository(settings, database=database)

    assert isinstance(repository, SQLitePlanRepository)


def test_a_file_store_cannot_confirm(tmp_path):
    with pytest.raises(ApplicationError) as raised:
        build_plan_activation_repository(_settings(tmp_path))

    assert raised.value.code == "CONFIGURATION_INVALID"


def test_a_sqlite_store_can_confirm(tmp_path):
    database = _database(tmp_path)
    settings = _settings(tmp_path, "sqlite")
    _record_import(database, settings.data_dir)

    assert hasattr(build_plan_activation_repository(settings, database=database),
                   "activate")


def test_an_unknown_mode_is_a_configuration_error(tmp_path):
    settings = _settings(tmp_path)
    object.__setattr__(settings, "plan_storage_mode", "postgres")

    with pytest.raises(ApplicationError) as raised:
        build_plan_repository(settings)

    assert raised.value.code == "CONFIGURATION_INVALID"


def test_the_import_record_reports_what_it_covered(tmp_path):
    database = _database(tmp_path)
    settings = _settings(tmp_path, "sqlite")
    _record_import(database, settings.data_dir, owners=3, plans=7)

    state = require_imported(settings, database)

    assert state["owner_count"] == 3 and state["plan_count"] == 7


def test_the_factory_opens_the_database_the_settings_name(tmp_path):
    settings = _settings(tmp_path, "sqlite")
    database = SQLiteDatabase(settings.database_path)
    run_migrations(database, RECORDS_MIGRATIONS)
    _record_import(database, settings.data_dir)

    repository = build_plan_repository(settings)

    assert isinstance(repository, SQLitePlanRepository)
    assert repository.database.path == settings.database_path


def test_an_import_record_in_another_database_does_not_count(tmp_path):
    # The record exists, but in a file the settings do not name. Reading the
    # process-wide default instead of the given settings is exactly how this
    # passes when it should not.
    settings = _settings(tmp_path, "sqlite")
    _record_import(_database(tmp_path), settings.data_dir)

    with pytest.raises(ApplicationError) as raised:
        build_plan_repository(settings)

    assert raised.value.code == "CONFIGURATION_INVALID"


def test_the_activation_store_reads_the_versioned_profile(tmp_path):
    # Confirmation has to read the constraints on its own transaction, so the
    # store it builds must carry that reader. Without it every candidate would be
    # refused for the wrong reason -- "no versioned store" instead of "this
    # constraint is not versioned yet".
    from backend.application.ports.profile_target_repository import (
        GoalVersionInput,
        ProfileVersionInput,
    )
    from backend.infrastructure.repositories.sqlite_profile_target_repository import (
        SQLiteProfileTargetRepository,
    )

    database = _database(tmp_path)
    settings = _settings(tmp_path, "sqlite")
    _record_import(database, settings.data_dir)
    profiles = SQLiteProfileTargetRepository(database)
    setup = profiles.bootstrap(
        "alice",
        ProfileVersionInput(age=30, height_cm=175.0, weight_kg=70.0,
                            energy_parameter="male", activity_level="moderate",
                            auto_target_disabled=False, safety_conditions=(),
                            effective_from="2026-10-01"),
        GoalVersionInput(goal="fat_loss", effective_from="2026-10-01"),
    )

    repository = build_plan_activation_repository(settings, database=database)

    with database.connection() as connection:
        snapshot = repository.constraints_reader(connection, "alice")
    assert snapshot.versions["goal"] == setup.goal.id
    # No safety row has been written, so the allergy list is present-but-unversioned
    # rather than absent: the value exists, its version does not.
    assert snapshot.versions["allergies_or_restrictions"] is None
    assert "available_equipment" not in snapshot.versions
