from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from backend.infrastructure.catalog.import_ledger import (
    CatalogImportLedger,
    CatalogMutationResult,
)
from backend.infrastructure.repositories.sqlite_exercise_catalog_repository import (
    _replace_search,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase


DEFAULT_SEED_PATH = (
    Path(__file__).parents[2]
    / "data"
    / "catalog"
    / "exercises.zh-CN.v1.json"
)


@dataclass(frozen=True)
class ExerciseSeedResult:
    inserted_count: int
    updated_count: int
    unchanged_count: int
    deactivated_count: int
    skipped: bool = False


def seed_bundled_exercises(
    database: SQLiteDatabase,
    path: Path = DEFAULT_SEED_PATH,
) -> ExerciseSeedResult:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("EXERCISE_SEED_SCHEMA_VERSION_UNSUPPORTED")
    dataset_version = _text(payload, "dataset_version")
    managed_sources = _text_list(payload.get("managed_sources"))
    raw_records = payload.get("exercises")
    if not isinstance(raw_records, list):
        raise ValueError("EXERCISE_SEED_RECORDS_INVALID")
    records = tuple(_record(item, managed_sources) for item in raw_records)
    identities = {
        (item["source_name"], item["source_record_id"]) for item in records
    }
    if len(identities) != len(records):
        raise ValueError("EXERCISE_SEED_SOURCE_ID_DUPLICATE")

    total = CatalogMutationResult()
    all_skipped = True
    ledger = CatalogImportLedger(database)
    for source_name in managed_sources:
        partition = tuple(
            record for record in records if record["source_name"] == source_name
        )
        versions = {str(record["dataset_version"]) for record in partition}
        if versions not in ({dataset_version}, set()):
            raise ValueError("EXERCISE_SEED_DATASET_VERSION_MISMATCH")
        checksum = _partition_checksum(source_name, dataset_version, partition)
        identities = {str(record["source_record_id"]) for record in partition}
        run = ledger.run(
            source_name,
            dataset_version,
            checksum,
            lambda connection, source_name=source_name, partition=partition,
            identities=identities: _import_partition(
                connection,
                source_name=source_name,
                records=partition,
                identities=identities,
            ),
        )
        all_skipped = all_skipped and run.status == "skipped"
        mutation = (
            CatalogMutationResult(unchanged_count=run.mutation.imported_count)
            if run.status == "skipped"
            else run.mutation
        )
        total = _add_results(total, mutation)
    return ExerciseSeedResult(
        total.inserted_count,
        total.updated_count,
        total.unchanged_count,
        total.deactivated_count,
        all_skipped,
    )


def _import_partition(
    connection,
    *,
    source_name: str,
    records: tuple[dict[str, object], ...],
    identities: set[str],
) -> CatalogMutationResult:
    inserted = updated = unchanged = deactivated = 0
    for record in records:
        existing = connection.execute(
            """
            SELECT id, content_hash, active FROM exercise_catalog
            WHERE owner_user_id IS NULL
              AND source_name = ? AND source_record_id = ?
            """,
            (record["source_name"], record["source_record_id"]),
        ).fetchone()
        if (
            existing is not None
            and existing["content_hash"] == record["content_hash"]
            and existing["active"] == 1
        ):
            unchanged += 1
            continue
        exercise_id = (
            existing["id"]
            if existing is not None
            else uuid5(
                NAMESPACE_URL,
                "exercise:"
                f"{record['source_name']}:{record['source_record_id']}",
            ).hex
        )
        if existing is None:
            connection.execute(
                """
                INSERT INTO exercise_catalog (
                    id, owner_user_id, source, source_name,
                    source_record_id, dataset_version, name,
                    exercise_type, primary_muscle,
                    secondary_muscles_json, met, license, attribution,
                    provenance_json, content_hash, active
                ) VALUES (
                    ?, NULL, 'public', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1
                )
                """,
                _parameters(exercise_id, record),
            )
            inserted += 1
        else:
            connection.execute(
                """
                UPDATE exercise_catalog
                SET dataset_version = ?, name = ?, exercise_type = ?,
                    primary_muscle = ?, secondary_muscles_json = ?,
                    met = ?, license = ?, attribution = ?,
                    provenance_json = ?, content_hash = ?, active = 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    record["dataset_version"], record["name"],
                    record["exercise_type"], record["primary_muscle"],
                    json.dumps(record["secondary_muscles"], ensure_ascii=False, separators=(",", ":")),
                    record["met"], record["license"], record["attribution"],
                    json.dumps(record["provenance"], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    record["content_hash"], exercise_id,
                ),
            )
            updated += 1
        _replace_search(
            connection,
            exercise_id=exercise_id,
            name=str(record["name"]),
            aliases=tuple(record["aliases"]),
            source_tokens=f"{record['source_name']} {record['source_record_id']}",
            id_factory=_seed_id_factory(exercise_id),
        )

    rows = connection.execute(
        """
        SELECT id, source_name, source_record_id
        FROM exercise_catalog
        WHERE owner_user_id IS NULL AND active = 1
          AND source_name = ?
        """,
        (source_name,),
    ).fetchall()
    for row in rows:
        if row["source_record_id"] in identities:
            continue
        connection.execute(
            """
            UPDATE exercise_catalog
            SET active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (row["id"],),
        )
        connection.execute(
            """
            DELETE FROM catalog_search
            WHERE catalog_kind = 'exercise' AND catalog_id = ?
            """,
            (row["id"],),
        )
        deactivated += 1
    return CatalogMutationResult(inserted, updated, unchanged, deactivated)


def _partition_checksum(
    source_name: str,
    dataset_version: str,
    records: tuple[dict[str, object], ...],
) -> str:
    canonical = json.dumps(
        {
            "source_name": source_name,
            "dataset_version": dataset_version,
            "records": sorted(
                records,
                key=lambda record: str(record["source_record_id"]),
            ),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _add_results(
    left: CatalogMutationResult,
    right: CatalogMutationResult,
) -> CatalogMutationResult:
    return CatalogMutationResult(
        inserted_count=left.inserted_count + right.inserted_count,
        updated_count=left.updated_count + right.updated_count,
        unchanged_count=left.unchanged_count + right.unchanged_count,
        deactivated_count=left.deactivated_count + right.deactivated_count,
        rejected_count=left.rejected_count + right.rejected_count,
    )


def _record(
    value: object,
    managed_sources: tuple[str, ...],
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("EXERCISE_SEED_RECORD_INVALID")
    source_name = _text(value, "source_name")
    if source_name not in managed_sources:
        raise ValueError("EXERCISE_SEED_SOURCE_UNMANAGED")
    exercise_type = _text(value, "exercise_type")
    if exercise_type not in {"strength", "cardio"}:
        raise ValueError("EXERCISE_SEED_TYPE_INVALID")
    met = value.get("met")
    if met is not None and (
        isinstance(met, bool)
        or not isinstance(met, (int, float))
        or met <= 0
    ):
        raise ValueError("EXERCISE_SEED_MET_INVALID")
    secondary = _text_list(value.get("secondary_muscles", []))
    aliases = _text_list(value.get("aliases", []))
    provenance = value.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("EXERCISE_SEED_PROVENANCE_INVALID")
    record: dict[str, object] = {
        "source_name": source_name,
        "source_record_id": _text(value, "source_record_id"),
        "dataset_version": _text(value, "dataset_version"),
        "name": _text(value, "name"),
        "exercise_type": exercise_type,
        "primary_muscle": _text(value, "primary_muscle"),
        "secondary_muscles": secondary,
        "met": met,
        "license": _text(value, "license"),
        "attribution": _text(value, "attribution"),
        "aliases": aliases,
        "provenance": provenance,
    }
    canonical = json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    record["content_hash"] = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    return record


def _parameters(
    exercise_id: str,
    record: dict[str, object],
) -> tuple[object, ...]:
    return (
        exercise_id,
        record["source_name"],
        record["source_record_id"],
        record["dataset_version"],
        record["name"],
        record["exercise_type"],
        record["primary_muscle"],
        json.dumps(
            record["secondary_muscles"],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        record["met"],
        record["license"],
        record["attribution"],
        json.dumps(
            record["provenance"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        record["content_hash"],
    )


def _seed_id_factory(exercise_id: str):
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return uuid5(
            NAMESPACE_URL,
            f"exercise-alias:{exercise_id}:{counter}",
        ).hex

    return next_id


def _text(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"EXERCISE_SEED_{key.upper()}_INVALID")
    return item.strip()


def _text_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("EXERCISE_SEED_TEXT_LIST_INVALID")
    output: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("EXERCISE_SEED_TEXT_INVALID")
        normalized = item.strip()
        if normalized not in output:
            output.append(normalized)
    return tuple(output)
