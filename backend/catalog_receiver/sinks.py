from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from backend.catalog_receiver.models import (
    CanonicalExerciseRecord,
    CanonicalFoodRecord,
    CanonicalRecord,
    MappingProfile,
    ReceiverError,
)
from backend.infrastructure.catalog.import_ledger import (
    CatalogImportError,
    CatalogImportLedger,
    CatalogMutationResult,
)
from backend.infrastructure.catalog.seed_exercises import seed_exercise_payload
from backend.infrastructure.catalog.seed_foods import seed_food_payload
from backend.infrastructure.sqlite.database import SQLiteDatabase


class SQLiteCatalogSink:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def import_records(
        self,
        profile: MappingProfile,
        records: tuple[CanonicalRecord, ...],
    ) -> dict[str, object]:
        try:
            if profile.catalog_kind == "food":
                result = seed_food_payload(
                    self.database,
                    _food_payload(profile, records),
                )
            else:
                result = seed_exercise_payload(
                    self.database,
                    _exercise_payload(profile, records),
                )
            retirement = self._retire_sources(profile)
        except (CatalogImportError, ValueError) as error:
            code = getattr(error, "code", str(error))
            raise ReceiverError(
                "DATABASE_IMPORT_FAILED",
                f"Catalog database import failed: {code}",
                exit_code=5,
            ) from error
        return {
            "status": "skipped" if result.skipped else "committed",
            **asdict(result),
            "retirement": retirement,
        }

    def _retire_sources(self, profile: MappingProfile) -> dict[str, object]:
        return retire_public_sources(
            self.database,
            catalog_kind=profile.catalog_kind,
            active_source=profile.source_name,
            retirement_version=profile.profile_version,
            source_names=profile.retired_sources,
        )


def retire_public_sources(
    database: SQLiteDatabase,
    *,
    catalog_kind: str,
    active_source: str,
    retirement_version: str,
    source_names: tuple[str, ...],
) -> dict[str, object]:
    retired_sources = tuple(dict.fromkeys(source_names))
    if not retired_sources:
        return {"status": "not_requested", "deactivated_count": 0}
    if active_source in retired_sources:
        raise ValueError("CATALOG_RETIREMENT_ACTIVE_SOURCE_INVALID")
    checksum = hashlib.sha256(
        json.dumps(
            {"catalog_kind": catalog_kind, "sources": retired_sources},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    run = CatalogImportLedger(database).run(
        f"catalog-retirement:{catalog_kind}:{active_source}",
        retirement_version,
        checksum,
        lambda connection: _retire_public_rows(
            connection,
            catalog_kind=catalog_kind,
            source_names=retired_sources,
        ),
    )
    return {
        "status": run.status,
        "deactivated_count": run.mutation.deactivated_count,
    }


def _food_payload(
    profile: MappingProfile,
    records: tuple[CanonicalRecord, ...],
) -> dict[str, object]:
    foods: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, CanonicalFoodRecord):
            raise ValueError("CATALOG_RECORD_KIND_MISMATCH")
        foods.append(record.model_dump(mode="json"))
    return {
        "schema_version": 1,
        "source_name": profile.source_name,
        "dataset_version": profile.dataset_version,
        "license": profile.license,
        "attribution": profile.attribution,
        "foods": foods,
    }


def _exercise_payload(
    profile: MappingProfile,
    records: tuple[CanonicalRecord, ...],
) -> dict[str, object]:
    exercises: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, CanonicalExerciseRecord):
            raise ValueError("CATALOG_RECORD_KIND_MISMATCH")
        exercises.append(record.model_dump(mode="json"))
    return {
        "schema_version": 1,
        "dataset_version": profile.dataset_version,
        "managed_sources": [profile.source_name],
        "exercises": exercises,
    }


def _retire_public_rows(
    connection,
    *,
    catalog_kind: str,
    source_names: tuple[str, ...],
) -> CatalogMutationResult:
    table = "food_catalog" if catalog_kind == "food" else "exercise_catalog"
    placeholders = ",".join("?" for _ in source_names)
    rows = connection.execute(
        f"""
        SELECT id FROM {table}
        WHERE owner_user_id IS NULL AND active = 1
          AND source_name IN ({placeholders})
        """,
        source_names,
    ).fetchall()
    if not rows:
        return CatalogMutationResult()
    identities = tuple(row["id"] for row in rows)
    id_placeholders = ",".join("?" for _ in identities)
    connection.execute(
        f"""
        UPDATE {table}
        SET active = 0, updated_at = CURRENT_TIMESTAMP
        WHERE owner_user_id IS NULL AND id IN ({id_placeholders})
        """,
        identities,
    )
    connection.execute(
        f"""
        DELETE FROM catalog_search
        WHERE catalog_kind = ? AND catalog_id IN ({id_placeholders})
        """,
        (catalog_kind, *identities),
    )
    return CatalogMutationResult(deactivated_count=len(identities))
