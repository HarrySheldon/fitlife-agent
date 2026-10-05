from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from backend.config import get_settings
from backend.catalog_receiver.sinks import retire_public_sources
from backend.infrastructure.catalog.seed_exercises import (
    DEFAULT_SEED_PATH as EXERCISE_SEED_PATH,
    seed_bundled_exercises,
)
from backend.infrastructure.catalog.seed_foods import (
    DEFAULT_SEED_PATH as FOOD_SEED_PATH,
    seed_bundled_foods,
)
from backend.infrastructure.migration.legacy_csv import LegacyCsvMigrator
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.runtime import get_database
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS
from backend.safety.gate import default_pack as load_safety_packs


logger = logging.getLogger("fitlife.startup")


@dataclass(frozen=True)
class StartupSummary:
    schema_version: int
    catalog_completed: int
    catalog_failed: int
    legacy_completed: int
    legacy_skipped: int
    legacy_failed: int
    duration_ms: int

    @property
    def status(self) -> str:
        return "degraded" if self.catalog_failed or self.legacy_failed else "ready"


_last_summary: StartupSummary | None = None


def run_startup(
    database: SQLiteDatabase | None = None,
    data_dir: Path | None = None,
) -> StartupSummary:
    global _last_summary
    started = time.monotonic()
    database = database or get_database()
    data_dir = Path(data_dir or get_settings().data_dir)

    # The safety rule packs are validated here rather than on first use. A broken,
    # missing or unsupported pack must refuse to start, not fail the first request
    # that happens to need the gate.
    phase_started = time.monotonic()
    _event(
        operation="safety_pack_load",
        version="1.0.0",
        status="started",
        counts={},
        duration_ms=0,
        checksum_prefix="",
    )
    pack = load_safety_packs()
    _event(
        operation="safety_pack_load",
        version=pack.pack_version,
        status="completed",
        counts={"concerns": len(pack.concerns), "policy_rules": len(pack.policy.rules)},
        duration_ms=_elapsed(phase_started),
        checksum_prefix="",
    )

    phase_started = time.monotonic()
    run_migrations(database, RECORDS_MIGRATIONS)
    schema_version = RECORDS_MIGRATIONS[-1].version
    _event(
        operation="schema_migration",
        version=str(schema_version),
        status="completed",
        counts={"applied_version": schema_version},
        duration_ms=_elapsed(phase_started),
        checksum_prefix=RECORDS_MIGRATIONS[-1].checksum[:12],
    )

    catalog_completed = catalog_failed = 0
    for operation, path, importer in (
        ("food_catalog_import", FOOD_SEED_PATH, seed_bundled_foods),
        ("exercise_catalog_import", EXERCISE_SEED_PATH, seed_bundled_exercises),
    ):
        phase_started = time.monotonic()
        version, checksum = _source_identity(path)
        retired_count = 0
        try:
            result = importer(database, path)
            if operation == "food_catalog_import":
                retirement = retire_public_sources(
                    database,
                    catalog_kind="food",
                    active_source="Taiwan FDA Food Nutrient Database",
                    retirement_version="1.0.0",
                    source_names=("USDA FoodData Central",),
                )
                retired_count = int(retirement["deactivated_count"])
        except Exception:
            catalog_failed += 1
            _event(
                operation=operation,
                version=version,
                status="failed",
                counts={},
                duration_ms=_elapsed(phase_started),
                checksum_prefix=checksum[:12],
            )
        else:
            catalog_completed += 1
            _event(
                operation=operation,
                version=version,
                status="skipped" if result.skipped else "completed",
                counts={
                    "inserted": result.inserted_count,
                    "updated": result.updated_count,
                    "unchanged": result.unchanged_count,
                    "deactivated": result.deactivated_count + retired_count,
                },
                duration_ms=_elapsed(phase_started),
                checksum_prefix=checksum[:12],
            )

    legacy_completed = legacy_skipped = legacy_failed = 0
    migrator = LegacyCsvMigrator(database, data_dir)
    for user_id in _registered_user_ids(data_dir):
        phase_started = time.monotonic()
        try:
            result = migrator.migrate_user(user_id)
        except Exception:
            legacy_failed += 1
            _event(
                operation="legacy_csv_cutover",
                version="legacy_csv_v1",
                status="failed",
                counts={},
                duration_ms=_elapsed(phase_started),
                checksum_prefix="",
            )
            continue
        if result.status == "completed":
            legacy_completed += 1
        elif result.status == "skipped":
            legacy_skipped += 1
        else:
            legacy_failed += 1
        _event(
            operation="legacy_csv_cutover",
            version="legacy_csv_v1",
            status=result.status,
            counts={
                "meal_rows": result.meal_rows,
                "meal_groups": result.meal_groups,
                "workout_rows": result.workout_rows,
            },
            duration_ms=_elapsed(phase_started),
            checksum_prefix=(result.backup_checksum or "")[:12],
        )

    _last_summary = StartupSummary(
        schema_version=schema_version,
        catalog_completed=catalog_completed,
        catalog_failed=catalog_failed,
        legacy_completed=legacy_completed,
        legacy_skipped=legacy_skipped,
        legacy_failed=legacy_failed,
        duration_ms=_elapsed(started),
    )
    _event(
        operation="startup",
        version=str(schema_version),
        status=_last_summary.status,
        counts=asdict(_last_summary),
        duration_ms=_last_summary.duration_ms,
        checksum_prefix=RECORDS_MIGRATIONS[-1].checksum[:12],
    )
    return _last_summary


def last_startup_summary() -> StartupSummary | None:
    return _last_summary


def _registered_user_ids(data_dir: Path) -> tuple[str, ...]:
    path = data_dir / "users.json"
    if not path.exists():
        return ()
    try:
        users = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _event(
            operation="legacy_user_discovery",
            version="legacy_csv_v1",
            status="failed",
            counts={},
            duration_ms=0,
            checksum_prefix="",
        )
        return ()
    if not isinstance(users, list):
        return ()
    return tuple(
        user_id
        for item in users
        if isinstance(item, dict)
        and isinstance((user_id := item.get("user_id")), str)
    )


def _source_identity(path: Path) -> tuple[str, str]:
    content = Path(path).read_bytes()
    try:
        payload = json.loads(content)
        version = str(payload.get("dataset_version", "unknown"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        version = "unknown"
    return version, hashlib.sha256(content).hexdigest()


def _event(
    *,
    operation: str,
    version: str,
    status: str,
    counts: dict[str, int],
    duration_ms: int,
    checksum_prefix: str,
) -> None:
    logger.info(
        json.dumps(
            {
                "operation": operation,
                "version": version,
                "status": status,
                "counts": counts,
                "duration_ms": duration_ms,
                "checksum_prefix": checksum_prefix,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _elapsed(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))
