# SQLite Records Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a versioned, transactional SQLite runtime and the complete empty schema required by the approved nutrition and training record design without changing current API behavior.

**Architecture:** Use Python's standard `sqlite3` driver for the embedded database, with foreign keys, WAL mode, a busy timeout, explicit transactions, and ordered application migrations. Keep persistence behind a small `SQLiteDatabase` adapter so later repositories depend on a stable transaction boundary instead of global connections. This phase creates schema only; CSV remains the active fitness repository until the later cutover plan.

**Tech Stack:** Python 3.12+, FastAPI lifespan, sqlite3, Pydantic Settings, pytest

---

## Scope And Open-Source Practice

This phase follows established embedded-SQLite practices used by mature local-first projects:

- one short-lived connection per operation instead of a process-global mutable cursor;
- `PRAGMA foreign_keys = ON`, WAL journaling and a bounded busy timeout;
- explicit `BEGIN IMMEDIATE` write transactions;
- append-only ordered migrations with stored checksums;
- database initialization in application lifespan, not as an import side effect.

Do not add SQLAlchemy, Alembic, background workers, repository cutover, CSV migration, catalog seed data, API changes or frontend code in this phase.

The project-local `.tmp` directory is ignored and is not copied into a new worktree. Create it once before running the commands below:

```powershell
New-Item -ItemType Directory -Force .tmp
```

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/config.py` | Resolve an optional SQLite path override and default path under `DATA_DIR` |
| `.env.example` | Document `SQLITE_DATABASE_PATH` |
| `backend/infrastructure/sqlite/__init__.py` | Export the SQLite infrastructure boundary |
| `backend/infrastructure/sqlite/database.py` | Connections, pragmas and transaction context |
| `backend/infrastructure/sqlite/migrations.py` | Migration type, checksum validation and ordered runner |
| `backend/infrastructure/sqlite/schema.py` | Versioned SQL statements for the approved record model |
| `backend/infrastructure/sqlite/runtime.py` | Settings-aware database construction and application initialization |
| `backend/main.py` | Run migrations in FastAPI lifespan |
| `backend/tests/test_config.py` | Configuration path tests |
| `backend/tests/infrastructure/test_sqlite_database.py` | Connection and transaction tests |
| `backend/tests/infrastructure/test_sqlite_migrations.py` | Ordering, idempotency and checksum tests |
| `backend/tests/infrastructure/test_records_schema.py` | Required tables, indexes and foreign-key contract |
| `backend/tests/test_database_startup.py` | FastAPI startup integration test |

### Task 1: Add SQLite Path Configuration

**Files:**
- Modify: `.env.example`
- Modify: `backend/config.py`
- Modify: `backend/tests/test_config.py`

- [x] **Step 1: Write failing configuration tests**

Append tests that prove the default is inside `DATA_DIR` and an explicit environment value wins:

```python
def test_sqlite_database_defaults_to_data_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("SQLITE_DATABASE_PATH", raising=False)
    settings = Settings(data_dir=tmp_path, _env_file=None)

    assert settings.database_path == tmp_path / "fitlife.sqlite3"


def test_sqlite_database_path_can_be_overridden(tmp_path, monkeypatch):
    override = tmp_path / "state" / "records.sqlite3"
    monkeypatch.setenv("SQLITE_DATABASE_PATH", str(override))
    settings = Settings(data_dir=tmp_path / "data", _env_file=None)

    assert settings.database_path == override


def test_blank_sqlite_database_path_uses_default(tmp_path, monkeypatch):
    monkeypatch.delenv("SQLITE_DATABASE_PATH", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"DATA_DIR={tmp_path / 'data'}\nSQLITE_DATABASE_PATH=\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.database_path == tmp_path / "data" / "fitlife.sqlite3"
```

- [x] **Step 2: Run the tests and verify RED**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest backend/tests/test_config.py -q -p no:cacheprovider --basetemp .tmp\pytest-sqlite-config
```

Expected: both new tests fail because `Settings.database_path` does not exist.

- [x] **Step 3: Implement the configuration boundary**

Add this field and property to `Settings` in `backend/config.py`:

```python
sqlite_database_path: Path | None = None

@property
def database_path(self) -> Path:
    return self.sqlite_database_path or self.data_dir / "fitlife.sqlite3"
```

Add a field-scoped pre-validator so only a blank SQLite override uses its default; do not change empty-value behavior for unrelated settings:

```python
@field_validator("sqlite_database_path", mode="before")
@classmethod
def blank_sqlite_database_path_uses_default(cls, value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value
```

Add this line to `.env.example` directly after the model settings:

```dotenv
SQLITE_DATABASE_PATH=
```

- [x] **Step 4: Run the focused tests and verify GREEN**

Run the Step 2 command again.

Expected: all tests in `backend/tests/test_config.py` pass.

- [x] **Step 5: Commit the configuration change**

```powershell
git add .env.example backend/config.py backend/tests/test_config.py
git commit -m "feat: configure embedded records database"
```

### Task 2: Implement Safe SQLite Connections And Transactions

**Files:**
- Create: `backend/infrastructure/sqlite/__init__.py`
- Create: `backend/infrastructure/sqlite/database.py`
- Create: `backend/tests/infrastructure/test_sqlite_database.py`

- [x] **Step 1: Write failing database behavior tests**

Create `backend/tests/infrastructure/test_sqlite_database.py`:

```python
import sqlite3

import pytest

from backend.infrastructure.sqlite.database import SQLiteDatabase


def test_connection_enables_required_pragmas(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")

    with database.connection() as connection:
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert foreign_keys == 1
    assert journal_mode == "wal"
    assert busy_timeout == 5000


def test_transaction_commits_all_statements(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    with database.transaction() as connection:
        connection.execute("CREATE TABLE values_table (value TEXT NOT NULL)")
        connection.execute("INSERT INTO values_table(value) VALUES (?)", ("saved",))

    with database.connection() as connection:
        assert connection.execute("SELECT value FROM values_table").fetchone()[0] == "saved"


def test_transaction_rolls_back_every_statement(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    with database.transaction() as connection:
        connection.execute("CREATE TABLE values_table (value TEXT NOT NULL)")

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute("INSERT INTO values_table(value) VALUES (?)", ("first",))
            connection.execute("INSERT INTO values_table(value) VALUES (NULL)")

    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM values_table").fetchone()[0] == 0
```

- [x] **Step 2: Run the tests and verify RED**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest backend/tests/infrastructure/test_sqlite_database.py -q -p no:cacheprovider --basetemp .tmp\pytest-sqlite-database
```

Expected: collection fails because the SQLite module does not exist.

- [x] **Step 3: Implement `SQLiteDatabase`**

Create `backend/infrastructure/sqlite/database.py`:

```python
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class SQLiteDatabase:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path,
            timeout=5,
            isolation_level=None,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA busy_timeout = 5000")
        except Exception:
            connection.close()
            raise
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()
```

Create `backend/infrastructure/sqlite/__init__.py`:

```python
from backend.infrastructure.sqlite.database import SQLiteDatabase

__all__ = ["SQLiteDatabase"]
```

- [x] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command again.

Expected: 5 tests pass, including normal context cleanup and initialization-failure cleanup.

- [x] **Step 5: Commit the database adapter**

```powershell
git add backend/infrastructure/sqlite backend/tests/infrastructure/test_sqlite_database.py
git commit -m "feat: add transactional SQLite adapter"
```

### Task 3: Add Ordered, Checksummed Migrations

**Files:**
- Create: `backend/infrastructure/sqlite/migrations.py`
- Create: `backend/tests/infrastructure/test_sqlite_migrations.py`

- [x] **Step 1: Write failing migration tests**

Create `backend/tests/infrastructure/test_sqlite_migrations.py`:

```python
import sqlite3

import pytest

from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import Migration, MigrationError, run_migrations


def test_migrations_run_in_version_order_and_only_once(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    migrations = (
        Migration(1, "create_example", ("CREATE TABLE example(id INTEGER PRIMARY KEY)",)),
        Migration(2, "add_name", ("ALTER TABLE example ADD COLUMN name TEXT",)),
    )

    run_migrations(database, migrations)
    run_migrations(database, migrations)

    with database.connection() as connection:
        applied = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        columns = connection.execute("PRAGMA table_info(example)").fetchall()

    assert [(row["version"], row["name"]) for row in applied] == [
        (1, "create_example"),
        (2, "add_name"),
    ]
    assert [row["name"] for row in columns] == ["id", "name"]


def test_changed_applied_migration_is_rejected(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    original = Migration(1, "create_example", ("CREATE TABLE example(id INTEGER)",))
    run_migrations(database, (original,))

    changed = Migration(1, "create_example", ("CREATE TABLE example(id TEXT)",))

    with pytest.raises(MigrationError, match="checksum"):
        run_migrations(database, (changed,))


def test_failed_migration_does_not_record_or_partially_apply(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    broken = Migration(
        1,
        "broken",
        (
            "CREATE TABLE first_table(id INTEGER)",
            "INSERT INTO missing_table(id) VALUES (1)",
        ),
    )

    with pytest.raises(sqlite3.OperationalError):
        run_migrations(database, (broken,))

    with database.connection() as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='first_table'"
        ).fetchone()
        count = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]

    assert table is None
    assert count == 0
```

- [x] **Step 2: Run the tests and verify RED**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest backend/tests/infrastructure/test_sqlite_migrations.py -q -p no:cacheprovider --basetemp .tmp\pytest-sqlite-migrations
```

Expected: collection fails because migration types do not exist.

- [x] **Step 3: Implement the migration runner**

Create `backend/infrastructure/sqlite/migrations.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable

from backend.infrastructure.sqlite.database import SQLiteDatabase


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        content = "\0".join((str(self.version), self.name, *self.statements))
        return sha256(content.encode("utf-8")).hexdigest()


def run_migrations(database: SQLiteDatabase, migrations: Iterable[Migration]) -> None:
    ordered = tuple(sorted(migrations, key=lambda item: item.version))
    _validate_versions(ordered)
    with database.transaction() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    for migration in ordered:
        with database.transaction() as connection:
            previous = connection.execute(
                "SELECT name, checksum FROM schema_migrations WHERE version = ?",
                (migration.version,),
            ).fetchone()
            if previous is not None:
                if previous["name"] != migration.name or previous["checksum"] != migration.checksum:
                    raise MigrationError(
                        f"Migration {migration.version} checksum or name changed after application"
                    )
                continue
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, name, checksum) VALUES (?, ?, ?)",
                (migration.version, migration.name, migration.checksum),
            )


def _validate_versions(migrations: tuple[Migration, ...]) -> None:
    versions = [migration.version for migration in migrations]
    if any(version < 1 for version in versions) or len(versions) != len(set(versions)):
        raise MigrationError("Migration versions must be unique positive integers")
```

- [x] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command again.

Expected: 3 tests pass.

- [x] **Step 5: Commit the migration runner**

```powershell
git add backend/infrastructure/sqlite/migrations.py backend/tests/infrastructure/test_sqlite_migrations.py
git commit -m "feat: add checksummed SQLite migrations"
```

Review amendments applied during execution: preflight the complete applied history before pending work, reject unknown applied versions, retain the locked per-version re-read, and use a bounded lock-only retry while enabling WAL. Concurrency regression tests cover simultaneous migration runners.

### Task 4: Create The Approved Empty Record Schema

**Files:**
- Create: `backend/infrastructure/sqlite/schema.py`
- Create: `backend/tests/infrastructure/test_records_schema.py`

- [x] **Step 1: Write the schema contract test**

Create `backend/tests/infrastructure/test_records_schema.py`:

```python
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


REQUIRED_TABLES = {
    "schema_migrations",
    "data_migrations",
    "user_profile_versions",
    "overall_goal_versions",
    "daily_target_versions",
    "daily_logs",
    "food_catalog",
    "exercise_catalog",
    "catalog_aliases",
    "catalog_favorites",
    "catalog_usage",
    "record_drafts",
    "meals",
    "meal_items",
    "training_sessions",
    "strength_exercises",
    "strength_sets",
    "cardio_items",
    "idempotency_keys",
    "catalog_imports",
}


def test_records_schema_contains_required_tables_and_fts(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    with database.connection() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        fts = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='catalog_search'"
        ).fetchone()

    assert REQUIRED_TABLES <= tables
    assert fts is not None and "VIRTUAL TABLE" in fts["sql"].upper()


def test_user_owned_children_cascade_from_their_aggregate(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO meals(id, user_id, log_date, name, meal_type, position, entry_method) "
            "VALUES ('meal-1', 'user-a', '2026-07-19', 'Lunch', 'lunch', 1, 'form')"
        )
        connection.execute(
            "INSERT INTO meal_items(id, meal_id, food_name, amount, unit, basis_type, "
            "calories, carbs, protein, fat, source) "
            "VALUES ('item-1', 'meal-1', 'Rice', 100, 'g', 'per_100g', 116, 25.9, 2.6, 0.3, 'user_custom')"
        )
        connection.execute("DELETE FROM meals WHERE id='meal-1'")

    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM meal_items").fetchone()[0] == 0
```

- [x] **Step 2: Run the contract test and verify RED**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest backend/tests/infrastructure/test_records_schema.py -q -p no:cacheprovider --basetemp .tmp\pytest-records-schema
```

Expected: collection fails because `RECORDS_MIGRATIONS` does not exist.

- [x] **Step 3: Define migration 1 in `schema.py`**

Create `backend/infrastructure/sqlite/schema.py` with one statement per tuple item. Do not split SQL strings dynamically:

```python
from backend.infrastructure.sqlite.migrations import Migration


RECORDS_MIGRATIONS = (
    Migration(
        version=1,
        name="create_records_schema",
        statements=(
            """
            CREATE TABLE data_migrations (
                migration_key TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
                source_backup_path TEXT,
                details_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(details_json)),
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            )
            """,
            """
            CREATE TABLE user_profile_versions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                age INTEGER NOT NULL CHECK (age >= 18 AND age <= 100),
                height_cm REAL NOT NULL CHECK (height_cm >= 120 AND height_cm <= 230),
                weight_kg REAL NOT NULL CHECK (weight_kg >= 30 AND weight_kg <= 300),
                energy_parameter TEXT NOT NULL CHECK (energy_parameter IN ('male', 'female', 'neutral')),
                activity_level TEXT NOT NULL CHECK (activity_level IN ('sedentary', 'light', 'moderate', 'high')),
                auto_target_disabled INTEGER NOT NULL DEFAULT 0 CHECK (auto_target_disabled IN (0, 1)),
                safety_conditions_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(safety_conditions_json)),
                effective_from TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, effective_from)
            )
            """,
            "CREATE INDEX idx_profile_versions_user_effective ON user_profile_versions(user_id, effective_from DESC)",
            """
            CREATE TABLE overall_goal_versions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                goal TEXT NOT NULL CHECK (goal IN ('fat_loss', 'maintenance', 'muscle_gain')),
                effective_from TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, effective_from)
            )
            """,
            "CREATE INDEX idx_goal_versions_user_effective ON overall_goal_versions(user_id, effective_from DESC)",
            """
            CREATE TABLE daily_target_versions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                profile_version_id TEXT,
                overall_goal_version_id TEXT,
                calories REAL NOT NULL CHECK (calories >= 800 AND calories <= 6000),
                carbs REAL NOT NULL CHECK (carbs >= 0 AND carbs <= 1000),
                protein REAL NOT NULL CHECK (protein >= 20 AND protein <= 400),
                fat REAL NOT NULL CHECK (fat >= 10 AND fat <= 300),
                source TEXT NOT NULL CHECK (source IN ('deterministic_calculation', 'manual', 'agent_confirmed')),
                formula_version TEXT,
                rationale_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(rationale_json)),
                effective_from TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(profile_version_id) REFERENCES user_profile_versions(id) ON DELETE SET NULL,
                FOREIGN KEY(overall_goal_version_id) REFERENCES overall_goal_versions(id) ON DELETE SET NULL,
                UNIQUE(user_id, effective_from)
            )
            """,
            "CREATE INDEX idx_target_versions_user_effective ON daily_target_versions(user_id, effective_from DESC)",
            "CREATE INDEX idx_target_versions_profile ON daily_target_versions(profile_version_id)",
            "CREATE INDEX idx_target_versions_goal ON daily_target_versions(overall_goal_version_id)",
            """
            CREATE TABLE daily_logs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                log_date TEXT NOT NULL,
                planned_meal_count INTEGER NOT NULL DEFAULT 3 CHECK (planned_meal_count >= 1 AND planned_meal_count <= 12),
                target_version_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(target_version_id) REFERENCES daily_target_versions(id) ON DELETE SET NULL,
                UNIQUE(user_id, log_date)
            )
            """,
            "CREATE INDEX idx_daily_logs_target ON daily_logs(target_version_id)",
            """
            CREATE TABLE food_catalog (
                id TEXT PRIMARY KEY,
                owner_user_id TEXT,
                source TEXT NOT NULL CHECK (source IN ('public', 'user_custom', 'agent_estimate', 'legacy_import')),
                source_name TEXT NOT NULL,
                source_record_id TEXT NOT NULL,
                dataset_version TEXT,
                name TEXT NOT NULL,
                basis_type TEXT NOT NULL CHECK (basis_type IN ('per_100g', 'per_100ml', 'per_serving')),
                basis_amount REAL NOT NULL CHECK (basis_amount > 0),
                unit TEXT NOT NULL,
                calories REAL NOT NULL CHECK (calories >= 0),
                carbs REAL NOT NULL CHECK (carbs >= 0),
                protein REAL NOT NULL CHECK (protein >= 0),
                fat REAL NOT NULL CHECK (fat >= 0),
                license TEXT,
                attribution TEXT,
                provenance_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(provenance_json)),
                content_hash TEXT,
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE UNIQUE INDEX idx_food_public_source ON food_catalog(source_name, source_record_id) WHERE owner_user_id IS NULL",
            "CREATE INDEX idx_food_owner_name ON food_catalog(owner_user_id, name)",
            """
            CREATE TABLE exercise_catalog (
                id TEXT PRIMARY KEY,
                owner_user_id TEXT,
                source TEXT NOT NULL CHECK (source IN ('public', 'user_custom', 'agent_estimate', 'legacy_import')),
                source_name TEXT NOT NULL,
                source_record_id TEXT NOT NULL,
                dataset_version TEXT,
                name TEXT NOT NULL,
                exercise_type TEXT NOT NULL CHECK (exercise_type IN ('strength', 'cardio')),
                primary_muscle TEXT NOT NULL,
                secondary_muscles_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(secondary_muscles_json)),
                met REAL CHECK (met IS NULL OR met > 0),
                license TEXT,
                attribution TEXT,
                provenance_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(provenance_json)),
                content_hash TEXT,
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE UNIQUE INDEX idx_exercise_public_source ON exercise_catalog(source_name, source_record_id) WHERE owner_user_id IS NULL",
            "CREATE INDEX idx_exercise_owner_name ON exercise_catalog(owner_user_id, name)",
            """
            CREATE TABLE catalog_aliases (
                id TEXT PRIMARY KEY,
                food_id TEXT,
                exercise_id TEXT,
                alias TEXT NOT NULL,
                normalized_alias TEXT NOT NULL,
                alias_kind TEXT NOT NULL CHECK (alias_kind IN ('zh', 'en', 'alias', 'pinyin')),
                FOREIGN KEY(food_id) REFERENCES food_catalog(id) ON DELETE CASCADE,
                FOREIGN KEY(exercise_id) REFERENCES exercise_catalog(id) ON DELETE CASCADE,
                CHECK ((food_id IS NOT NULL) != (exercise_id IS NOT NULL))
            )
            """,
            "CREATE INDEX idx_catalog_alias_food ON catalog_aliases(food_id)",
            "CREATE INDEX idx_catalog_alias_exercise ON catalog_aliases(exercise_id)",
            "CREATE INDEX idx_catalog_alias_normalized ON catalog_aliases(normalized_alias)",
            """
            CREATE TABLE catalog_favorites (
                user_id TEXT NOT NULL,
                catalog_kind TEXT NOT NULL CHECK (catalog_kind IN ('food', 'exercise')),
                catalog_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(user_id, catalog_kind, catalog_id)
            )
            """,
            """
            CREATE TABLE catalog_usage (
                user_id TEXT NOT NULL,
                catalog_kind TEXT NOT NULL CHECK (catalog_kind IN ('food', 'exercise')),
                catalog_id TEXT NOT NULL,
                use_count INTEGER NOT NULL DEFAULT 1 CHECK (use_count >= 1),
                last_used_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(user_id, catalog_kind, catalog_id)
            )
            """,
            "CREATE INDEX idx_catalog_usage_recent ON catalog_usage(user_id, catalog_kind, last_used_at DESC)",
            """
            CREATE TABLE record_drafts (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('meal', 'workout', 'smart_entry', 'daily_target')),
                schema_version INTEGER NOT NULL CHECK (schema_version >= 1),
                payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
                version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
                agent_status TEXT NOT NULL DEFAULT 'not_requested' CHECK (agent_status IN ('not_requested', 'running', 'completed', 'failed')),
                agent_prompt_version TEXT,
                agent_model TEXT,
                agent_metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(agent_metadata_json)),
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX idx_record_drafts_user_expiry ON record_drafts(user_id, expires_at)",
            """
            CREATE TABLE meals (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                log_date TEXT NOT NULL,
                name TEXT NOT NULL,
                meal_type TEXT NOT NULL,
                position INTEGER NOT NULL CHECK (position >= 1),
                entry_method TEXT NOT NULL CHECK (entry_method IN ('form', 'smart_entry', 'csv', 'legacy')),
                legacy_source_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, log_date, position)
            )
            """,
            "CREATE INDEX idx_meals_user_date ON meals(user_id, log_date)",
            """
            CREATE TABLE meal_items (
                id TEXT PRIMARY KEY,
                meal_id TEXT NOT NULL,
                catalog_food_id TEXT,
                food_name TEXT NOT NULL,
                amount REAL NOT NULL CHECK (amount > 0),
                unit TEXT NOT NULL,
                basis_type TEXT NOT NULL CHECK (basis_type IN ('per_100g', 'per_100ml', 'per_serving')),
                calories REAL NOT NULL CHECK (calories >= 0),
                carbs REAL NOT NULL CHECK (carbs >= 0),
                protein REAL NOT NULL CHECK (protein >= 0),
                fat REAL NOT NULL CHECK (fat >= 0),
                source TEXT NOT NULL CHECK (source IN ('public', 'user_custom', 'agent_estimate', 'legacy_import')),
                is_estimate INTEGER NOT NULL DEFAULT 0 CHECK (is_estimate IN (0, 1)),
                uncertainty_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(uncertainty_json)),
                assumptions_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(assumptions_json)),
                provenance_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(provenance_json)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(meal_id) REFERENCES meals(id) ON DELETE CASCADE,
                FOREIGN KEY(catalog_food_id) REFERENCES food_catalog(id) ON DELETE SET NULL
            )
            """,
            "CREATE INDEX idx_meal_items_meal ON meal_items(meal_id)",
            "CREATE INDEX idx_meal_items_catalog ON meal_items(catalog_food_id)",
            """
            CREATE TABLE training_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                log_date TEXT NOT NULL,
                title TEXT NOT NULL,
                started_at TEXT,
                duration_min REAL CHECK (duration_min IS NULL OR duration_min > 0),
                intensity TEXT CHECK (intensity IS NULL OR intensity IN ('low', 'medium', 'high')),
                entry_method TEXT NOT NULL CHECK (entry_method IN ('form', 'smart_entry', 'csv', 'legacy')),
                estimated_calories REAL CHECK (estimated_calories IS NULL OR estimated_calories >= 0),
                estimate_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(estimate_json)),
                legacy_source_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX idx_training_sessions_user_date ON training_sessions(user_id, log_date)",
            """
            CREATE TABLE strength_exercises (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                catalog_exercise_id TEXT,
                exercise_name TEXT NOT NULL,
                primary_muscle TEXT NOT NULL,
                secondary_muscles_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(secondary_muscles_json)),
                estimated_calories REAL CHECK (estimated_calories IS NULL OR estimated_calories >= 0),
                estimate_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(estimate_json)),
                provenance_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(provenance_json)),
                position INTEGER NOT NULL CHECK (position >= 1),
                FOREIGN KEY(session_id) REFERENCES training_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY(catalog_exercise_id) REFERENCES exercise_catalog(id) ON DELETE SET NULL
            )
            """,
            "CREATE INDEX idx_strength_exercises_session ON strength_exercises(session_id)",
            "CREATE INDEX idx_strength_exercises_catalog ON strength_exercises(catalog_exercise_id)",
            """
            CREATE TABLE strength_sets (
                id TEXT PRIMARY KEY,
                strength_exercise_id TEXT NOT NULL,
                set_number INTEGER NOT NULL CHECK (set_number >= 1),
                reps INTEGER NOT NULL CHECK (reps >= 1),
                load_kg REAL CHECK (load_kg IS NULL OR load_kg >= 0),
                bodyweight INTEGER NOT NULL DEFAULT 0 CHECK (bodyweight IN (0, 1)),
                FOREIGN KEY(strength_exercise_id) REFERENCES strength_exercises(id) ON DELETE CASCADE,
                UNIQUE(strength_exercise_id, set_number)
            )
            """,
            "CREATE INDEX idx_strength_sets_exercise ON strength_sets(strength_exercise_id)",
            """
            CREATE TABLE cardio_items (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                catalog_exercise_id TEXT,
                activity_name TEXT NOT NULL,
                duration_min REAL NOT NULL CHECK (duration_min > 0),
                device_calories REAL CHECK (device_calories IS NULL OR device_calories >= 0),
                met REAL CHECK (met IS NULL OR met > 0),
                estimated_calories REAL CHECK (estimated_calories IS NULL OR estimated_calories >= 0),
                estimate_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(estimate_json)),
                provenance_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(provenance_json)),
                position INTEGER NOT NULL CHECK (position >= 1),
                FOREIGN KEY(session_id) REFERENCES training_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY(catalog_exercise_id) REFERENCES exercise_catalog(id) ON DELETE SET NULL
            )
            """,
            "CREATE INDEX idx_cardio_items_session ON cardio_items(session_id)",
            "CREATE INDEX idx_cardio_items_catalog ON cardio_items(catalog_exercise_id)",
            """
            CREATE TABLE idempotency_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                response_json TEXT NOT NULL CHECK (json_valid(response_json)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, operation, idempotency_key)
            )
            """,
            """
            CREATE TABLE catalog_imports (
                source_name TEXT NOT NULL,
                dataset_version TEXT NOT NULL,
                checksum TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
                imported_count INTEGER NOT NULL DEFAULT 0 CHECK (imported_count >= 0),
                rejected_count INTEGER NOT NULL DEFAULT 0 CHECK (rejected_count >= 0),
                details_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(details_json)),
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                PRIMARY KEY(source_name, dataset_version)
            )
            """,
            """
            CREATE VIRTUAL TABLE catalog_search USING fts5(
                catalog_kind UNINDEXED,
                catalog_id UNINDEXED,
                name,
                aliases,
                pinyin,
                source_tokens
            )
            """,
        ),
    ),
)
```

The schema intentionally has no identity-table foreign key because authentication remains file-backed in this program. User deletion will issue explicit repository cleanup for every `user_id`-owned table in the later cutover phase.

- [x] **Step 4: Run schema and migration tests**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest backend/tests/infrastructure/test_records_schema.py backend/tests/infrastructure/test_sqlite_migrations.py -q -p no:cacheprovider --basetemp .tmp\pytest-records-schema-green
```

Expected: 5 tests pass.

- [x] **Step 5: Commit the empty schema**

```powershell
git add backend/infrastructure/sqlite/schema.py backend/tests/infrastructure/test_records_schema.py
git commit -m "feat: define versioned fitness records schema"
```

Review amendments applied during execution: user-owned version references use composite
foreign keys, historical target provenance is protected with restricted deletion, catalog
ownership is constrained by source, favorites and usage have relational catalog targets,
training item positions are unique per session, and behavioral tests cover ownership,
cascades, foreign keys, and FTS search.

### Task 5: Initialize The Database In FastAPI Lifespan

**Files:**
- Create: `backend/infrastructure/sqlite/runtime.py`
- Modify: `backend/main.py`
- Create: `backend/tests/test_database_startup.py`

- [ ] **Step 1: Write a failing startup test**

Create `backend/tests/test_database_startup.py`:

```python
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.infrastructure.sqlite.runtime import get_database
from backend.main import create_app


def test_application_startup_creates_and_migrates_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SQLITE_DATABASE_PATH", raising=False)
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200

    database_path = tmp_path / "fitlife.sqlite3"
    assert database_path.exists()
    with get_database().connection() as connection:
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert [row["version"] for row in versions] == [1]

    get_settings.cache_clear()
```

- [ ] **Step 2: Run the startup test and verify RED**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest backend/tests/test_database_startup.py -q -p no:cacheprovider --basetemp .tmp\pytest-database-startup
```

Expected: collection fails because `runtime.get_database` does not exist.

- [ ] **Step 3: Add the runtime factory**

Create `backend/infrastructure/sqlite/runtime.py`:

```python
from backend.config import get_settings
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


def get_database() -> SQLiteDatabase:
    return SQLiteDatabase(get_settings().database_path)


def initialize_database() -> None:
    run_migrations(get_database(), RECORDS_MIGRATIONS)
```

Change `create_app()` in `backend/main.py` to use lifespan initialization:

```python
from contextlib import asynccontextmanager

from backend.infrastructure.sqlite.runtime import initialize_database


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="FitLife Agent API", version="0.1.0", lifespan=lifespan)
```

Do not initialize the database at module import time, do not alter `/health`, and do not switch existing repositories.

- [ ] **Step 4: Run startup and API regression tests**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest backend/tests/test_database_startup.py backend/tests/test_api_basic.py backend/tests/test_auth_calendar_api.py -q -p no:cacheprovider --basetemp .tmp\pytest-database-startup-green
```

Expected: all selected tests pass and current CSV-backed endpoints retain their response contracts.

- [ ] **Step 5: Commit lifespan initialization**

```powershell
git add backend/infrastructure/sqlite/runtime.py backend/main.py backend/tests/test_database_startup.py
git commit -m "feat: initialize records database on startup"
```

### Task 6: Verify The Foundation And Document The Next Boundary

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-07-19-today-records-program-roadmap.md`

- [ ] **Step 1: Document runtime behavior**

Add a concise README section stating:

```markdown
### Records database

The backend creates `backend/data/fitlife.sqlite3` on startup and applies checksummed schema migrations. Set `SQLITE_DATABASE_PATH` only when the database must live elsewhere. CSV remains the active record source until the migration phase completes; do not delete existing user CSV files.
```

Mark Phase 1 as complete in the roadmap only after every verification command below passes.

- [ ] **Step 2: Run complete backend verification**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider --basetemp .tmp\pytest-sqlite-foundation-full
```

Expected: all backend tests pass. The existing Starlette `httpx` deprecation warning may remain; test failures may not.

- [ ] **Step 3: Validate Docker configuration and application startup**

Run:

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/health
```

Expected:

- Compose configuration succeeds;
- backend and frontend containers are `Up`;
- health response has `success=True` and `data.status=ok`;
- `backend/data/fitlife.sqlite3` exists on the bind-mounted data directory.

- [ ] **Step 4: Confirm migration idempotency through restart**

Run:

```powershell
docker compose restart backend
Invoke-RestMethod http://127.0.0.1:8000/health
```

Expected: the backend restarts successfully and migration 1 is not reapplied or rejected.

- [ ] **Step 5: Commit documentation and roadmap evidence**

```powershell
git add README.md docs/superpowers/plans/2026-07-19-today-records-program-roadmap.md
git commit -m "docs: verify SQLite records foundation"
```

## Completion Criteria

This plan is complete only when:

- the main worktree was clean before the branch was created;
- SQLite connection and migration tests pass;
- the full backend suite passes;
- Docker startup and restart both pass;
- current API responses remain unchanged;
- no CSV is migrated, deleted or made stale in this phase;
- no account export behavior is added or changed;
- the feature worktree is clean after the final commit.
