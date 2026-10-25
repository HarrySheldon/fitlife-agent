"""Which plan store is authoritative, decided in one place.

Two rules, and both exist to stop a specific silent failure.

**One source, chosen once.** The deployment names the authority with
``plan_storage_mode``. Callers never fall back: a request must not read a file
because a database row was missing, and it must not read a database because a
file was easier. A fallback would turn "this user's plans are in the other
store" into "this user has no plans", which is the one answer that looks normal
and is wrong.

**The switch is a data-migration switch, not a feature flag.** ``sqlite`` is
refused until an import has completed against *this* data directory. Pointing a
deployment at an empty database would make every existing plan disappear from
the UI while the files sat untouched on disk -- an outage that reads like data
loss. Requiring the import record makes the pairing explicit and the failure
loud.

``file`` stays the default. Nothing about enabling the coach implies moving the
data, and a merge must never migrate a database as a side effect.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal

from backend.application.ports.plan_repository import PlanActivationRepository, PlanRepository
from backend.domain.errors import configuration_error
from backend.infrastructure.repositories.file_plan_repository import FilePlanRepository

PlanStorageMode = Literal["file", "sqlite"]
_MODES = ("file", "sqlite")


def _mode(settings) -> str:
    mode = getattr(settings, "plan_storage_mode", "file")
    if mode not in _MODES:
        # pydantic rejects it at load time; this catches a hand-built Settings in
        # a test or a caller that mutated the object afterwards.
        raise configuration_error(f"plan_storage_mode must be one of {_MODES}.")
    return mode


def _import_state(database) -> dict | None:
    try:
        with database.connection() as connection:
            row = connection.execute(
                "SELECT data_dir, completed_at, owner_count, plan_count, draft_count "
                "FROM plan_import_state WHERE id=1"
            ).fetchone()
    except sqlite3.OperationalError:
        # No schema at all. That is the strongest possible evidence that no
        # import completed here, and it must read as "refused", not as a crash.
        return None
    return None if row is None else dict(row)


def _resolved(path) -> str:
    return str(Path(path).resolve())


def require_imported(settings, database) -> dict:
    """The import record, or a refusal.

    A record for a *different* directory is a refusal too: it proves an import
    happened somewhere, not that it covered the data this deployment serves.
    """
    state = _import_state(database)
    if state is None:
        raise configuration_error(
            "plan_storage_mode='sqlite' requires a completed legacy plan import; "
            "run backend.infrastructure.sqlite.import_legacy_plans --apply first.")
    if _resolved(state["data_dir"]) != _resolved(settings.data_dir):
        raise configuration_error(
            "plan_storage_mode='sqlite' requires an import of the configured data "
            "directory; the recorded import covers a different one.")
    return state


def build_plan_repository(settings, *, database=None) -> PlanRepository:
    """The store every reader and writer must use."""
    mode = _mode(settings)
    if mode == "file":
        return FilePlanRepository(Path(settings.data_dir))
    database = database or _database(settings)
    require_imported(settings, database)
    return _sqlite_repository(database)


def build_plan_activation_repository(settings, *, database=None) -> PlanActivationRepository:
    """The store, if it can confirm a candidate atomically.

    A file store cannot compare-and-swap a head, so it has no ``activate``. The
    refusal happens here rather than inside the file repository, because a store
    that grew a fake ``activate`` would let two processes both confirm the same
    base and both report success.

    The activation store is given the versioned constraint reader as well, because
    the two must be the same database: a confirmation that versioned its head but
    not its constraints would refuse every candidate on a correctly configured
    deployment, and one that skipped the check would approve on a file nobody can
    re-read.
    """
    mode = _mode(settings)
    if mode == "file":
        raise configuration_error(
            "Plan confirmation requires plan_storage_mode='sqlite'.")
    database = database or _database(settings)
    require_imported(settings, database)
    return _activation_repository(database)


def _database(settings):
    """The deployment's own database file, not the process-wide default.

    Reading ``get_settings()`` here would make the factory ignore the settings it
    was handed -- which is how a test or a second deployment ends up importing
    one database and serving another.
    """
    from backend.infrastructure.sqlite.database import SQLiteDatabase
    return SQLiteDatabase(Path(settings.database_path))


def _sqlite_repository(database):
    from backend.infrastructure.repositories.sqlite_plan_repository import (
        SQLitePlanRepository,
    )
    return SQLitePlanRepository(database)


def _activation_repository(database):
    from backend.infrastructure.repositories.sqlite_plan_repository import (
        SQLitePlanRepository,
    )
    from backend.infrastructure.repositories.sqlite_profile_target_repository import (
        SQLiteProfileTargetRepository,
    )

    profiles = SQLiteProfileTargetRepository(database)
    return SQLitePlanRepository(
        database, constraints_reader=profiles.constraint_snapshot_with)
