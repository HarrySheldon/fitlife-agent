from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

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
        content = "\0".join(
            (str(self.version), self.name, *self.statements)
        ).encode("utf-8")
        return hashlib.sha256(content).hexdigest()


def _validate_applied_migration(
    migration: Migration, *, applied_name: str, applied_checksum: str
) -> None:
    differences = []
    if applied_name != migration.name:
        differences.append("name")
    if applied_checksum != migration.checksum:
        differences.append("checksum")
    if differences:
        fields = " and ".join(differences)
        raise MigrationError(f"migration {migration.version} {fields} mismatch")


def run_migrations(
    database: SQLiteDatabase, migrations: Iterable[Migration]
) -> None:
    ordered_migrations = list(migrations)
    versions = [migration.version for migration in ordered_migrations]
    if any(
        not isinstance(version, int) or isinstance(version, bool) or version <= 0
        for version in versions
    ):
        raise MigrationError("migration versions must be positive integers")
    if len(set(versions)) != len(versions):
        raise MigrationError("migration versions must be unique")
    ordered_migrations.sort(key=lambda migration: migration.version)
    migrations_by_version = {
        migration.version: migration for migration in ordered_migrations
    }

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

    with database.transaction() as connection:
        applied_migrations = connection.execute(
            "SELECT version, name, checksum FROM schema_migrations"
        ).fetchall()
        for applied in applied_migrations:
            migration = migrations_by_version.get(applied["version"])
            if migration is None:
                raise MigrationError(
                    f"applied migration {applied['version']} is unknown "
                    "(not supplied)"
                )
            _validate_applied_migration(
                migration,
                applied_name=applied["name"],
                applied_checksum=applied["checksum"],
            )

    for migration in ordered_migrations:
        with database.transaction() as connection:
            applied = connection.execute(
                "SELECT name, checksum FROM schema_migrations WHERE version = ?",
                (migration.version,),
            ).fetchone()
            if applied is not None:
                _validate_applied_migration(
                    migration,
                    applied_name=applied["name"],
                    applied_checksum=applied["checksum"],
                )
                continue

            for statement in migration.statements:
                connection.execute(statement)

            connection.execute(
                """
                INSERT INTO schema_migrations (version, name, checksum)
                VALUES (?, ?, ?)
                """,
                (migration.version, migration.name, migration.checksum),
            )
