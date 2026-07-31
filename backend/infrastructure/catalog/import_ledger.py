from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Literal

from backend.infrastructure.sqlite.database import SQLiteDatabase


class CatalogImportError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CatalogMutationResult:
    inserted_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    deactivated_count: int = 0
    rejected_count: int = 0

    @property
    def imported_count(self) -> int:
        return self.inserted_count + self.updated_count + self.unchanged_count


@dataclass(frozen=True)
class CatalogImportRun:
    status: Literal["completed", "skipped"]
    mutation: CatalogMutationResult


CatalogImporter = Callable[[sqlite3.Connection], CatalogMutationResult]


class CatalogImportLedger:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def run(
        self,
        source_name: str,
        dataset_version: str,
        checksum: str,
        importer: CatalogImporter,
    ) -> CatalogImportRun:
        source = _required_text(source_name, "CATALOG_IMPORT_SOURCE_INVALID")
        version = _required_text(
            dataset_version,
            "CATALOG_IMPORT_VERSION_INVALID",
        )
        digest = checksum.casefold()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise CatalogImportError("CATALOG_IMPORT_CHECKSUM_INVALID")

        try:
            with self.database.transaction() as connection:
                existing = connection.execute(
                    """
                    SELECT checksum, status, details_json
                    FROM catalog_imports
                    WHERE source_name = ? AND dataset_version = ?
                    """,
                    (source, version),
                ).fetchone()
                if existing is not None and existing["status"] == "completed":
                    if existing["checksum"] != digest:
                        raise CatalogImportError(
                            "CATALOG_IMPORT_CHECKSUM_MISMATCH"
                        )
                    return CatalogImportRun(
                        status="skipped",
                        mutation=_saved_mutation(existing["details_json"]),
                    )

                connection.execute(
                    """
                    INSERT INTO catalog_imports (
                        source_name, dataset_version, checksum, status,
                        imported_count, rejected_count, details_json,
                        started_at, completed_at
                    ) VALUES (?, ?, ?, 'running', 0, 0, '{}', CURRENT_TIMESTAMP, NULL)
                    ON CONFLICT(source_name, dataset_version) DO UPDATE SET
                        checksum = excluded.checksum,
                        status = 'running',
                        imported_count = 0,
                        rejected_count = 0,
                        details_json = '{}',
                        started_at = CURRENT_TIMESTAMP,
                        completed_at = NULL
                    """,
                    (source, version, digest),
                )
                mutation = importer(connection)
                if not isinstance(mutation, CatalogMutationResult):
                    raise TypeError("catalog importer returned an invalid result")
                details = json.dumps(
                    asdict(mutation),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                connection.execute(
                    """
                    UPDATE catalog_imports
                    SET status = 'completed', imported_count = ?,
                        rejected_count = ?, details_json = ?,
                        completed_at = CURRENT_TIMESTAMP
                    WHERE source_name = ? AND dataset_version = ?
                    """,
                    (
                        mutation.imported_count,
                        mutation.rejected_count,
                        details,
                        source,
                        version,
                    ),
                )
                return CatalogImportRun("completed", mutation)
        except CatalogImportError:
            raise
        except Exception as error:
            self._record_failure(source, version, digest)
            raise CatalogImportError("CATALOG_IMPORT_FAILED") from error

    def _record_failure(
        self,
        source_name: str,
        dataset_version: str,
        checksum: str,
    ) -> None:
        details = json.dumps(
            {"error_code": "CATALOG_IMPORT_FAILED"},
            separators=(",", ":"),
        )
        try:
            with self.database.transaction() as connection:
                existing = connection.execute(
                    """
                    SELECT status FROM catalog_imports
                    WHERE source_name = ? AND dataset_version = ?
                    """,
                    (source_name, dataset_version),
                ).fetchone()
                if existing is not None and existing["status"] == "completed":
                    return
                connection.execute(
                    """
                    INSERT INTO catalog_imports (
                        source_name, dataset_version, checksum, status,
                        imported_count, rejected_count, details_json,
                        started_at, completed_at
                    ) VALUES (?, ?, ?, 'failed', 0, 0, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(source_name, dataset_version) DO UPDATE SET
                        checksum = excluded.checksum,
                        status = 'failed',
                        imported_count = 0,
                        rejected_count = 0,
                        details_json = excluded.details_json,
                        completed_at = CURRENT_TIMESTAMP
                    """,
                    (source_name, dataset_version, checksum, details),
                )
        except Exception:
            # Preserve the original import failure even if observability storage fails.
            return


def _required_text(value: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogImportError(code)
    return value.strip()


def _saved_mutation(value: str) -> CatalogMutationResult:
    try:
        raw = json.loads(value)
        return CatalogMutationResult(
            **{
                field: int(raw.get(field, 0))
                for field in CatalogMutationResult.__dataclass_fields__
            }
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return CatalogMutationResult()
