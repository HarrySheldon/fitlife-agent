from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from backend.domain.meals import FoodDefinition
from backend.infrastructure.catalog.import_ledger import (
    CatalogImportLedger,
    CatalogMutationResult,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase


DEFAULT_SEED_PATH = (
    Path(__file__).parents[2]
    / "data"
    / "catalog"
    / "foods.zh-CN.v1.json"
)


@dataclass(frozen=True)
class FoodSeedResult:
    inserted_count: int
    updated_count: int
    unchanged_count: int
    deactivated_count: int
    skipped: bool = False


def seed_bundled_foods(
    database: SQLiteDatabase,
    path: Path = DEFAULT_SEED_PATH,
) -> FoodSeedResult:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return seed_food_payload(database, payload)


def seed_food_payload(
    database: SQLiteDatabase,
    payload: dict[str, object],
) -> FoodSeedResult:
    if payload.get("schema_version") != 1:
        raise ValueError("FOOD_SEED_SCHEMA_VERSION_UNSUPPORTED")
    source_name = _required_text(payload, "source_name")
    dataset_version = _required_text(payload, "dataset_version")
    license_name = _required_text(payload, "license")
    attribution = _required_text(payload, "attribution")
    foods = payload.get("foods")
    if not isinstance(foods, list):
        raise ValueError("FOOD_SEED_RECORDS_INVALID")
    records: list[dict[str, object]] = []
    source_ids: set[str] = set()
    for raw_food in foods:
        record = _validated_record(
            raw_food,
            source_name=source_name,
            dataset_version=dataset_version,
            license_name=license_name,
            attribution=attribution,
        )
        source_record_id = str(record["source_record_id"])
        if source_record_id in source_ids:
            raise ValueError("FOOD_SEED_SOURCE_ID_DUPLICATE")
        source_ids.add(source_record_id)
        records.append(record)

    checksum = _partition_checksum(source_name, dataset_version, records)
    run = CatalogImportLedger(database).run(
        source_name,
        dataset_version,
        checksum,
        lambda connection: _import_records(
            connection,
            source_name=source_name,
            records=records,
            source_ids=source_ids,
        ),
    )
    mutation = (
        CatalogMutationResult(unchanged_count=run.mutation.imported_count)
        if run.status == "skipped"
        else run.mutation
    )
    return FoodSeedResult(
        inserted_count=mutation.inserted_count,
        updated_count=mutation.updated_count,
        unchanged_count=mutation.unchanged_count,
        deactivated_count=mutation.deactivated_count,
        skipped=run.status == "skipped",
    )


def _import_records(
    connection: sqlite3.Connection,
    *,
    source_name: str,
    records: list[dict[str, object]],
    source_ids: set[str],
) -> CatalogMutationResult:
    inserted = updated = unchanged = deactivated = 0
    for record in records:
        existing = connection.execute(
            """
            SELECT id, content_hash, active
            FROM food_catalog
            WHERE owner_user_id IS NULL
              AND source_name = ?
              AND source_record_id = ?
            """,
            (source_name, record["source_record_id"]),
        ).fetchone()
        if (
            existing is not None
            and existing["content_hash"] == record["content_hash"]
            and existing["active"] == 1
        ):
            unchanged += 1
            continue

        if existing is None:
            food_id = uuid5(
                NAMESPACE_URL,
                f"food:{source_name}:{record['source_record_id']}",
            ).hex
            _insert_food(connection, food_id, record)
            inserted += 1
        else:
            food_id = existing["id"]
            _update_food(connection, food_id, record)
            updated += 1
        _replace_aliases_and_search(connection, food_id, record)

    existing_source_rows = connection.execute(
        """
        SELECT id, source_record_id
        FROM food_catalog
        WHERE owner_user_id IS NULL
          AND source_name = ?
          AND active = 1
        """,
        (source_name,),
    ).fetchall()
    for existing_source in existing_source_rows:
        if existing_source["source_record_id"] in source_ids:
            continue
        connection.execute(
            """
            UPDATE food_catalog
            SET active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (existing_source["id"],),
        )
        connection.execute(
            """
            DELETE FROM catalog_search
            WHERE catalog_kind = 'food' AND catalog_id = ?
            """,
            (existing_source["id"],),
        )
        deactivated += 1
    return CatalogMutationResult(
        inserted_count=inserted,
        updated_count=updated,
        unchanged_count=unchanged,
        deactivated_count=deactivated,
    )


def _partition_checksum(
    source_name: str,
    dataset_version: str,
    records: list[dict[str, object]],
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


def _validated_record(
    raw_food: object,
    *,
    source_name: str,
    dataset_version: str,
    license_name: str,
    attribution: str,
) -> dict[str, object]:
    if not isinstance(raw_food, dict):
        raise ValueError("FOOD_SEED_RECORD_INVALID")
    record_source_name = _required_text(raw_food, "source_name")
    record_dataset_version = _required_text(raw_food, "dataset_version")
    record_license = _required_text(raw_food, "license")
    record_attribution = _required_text(raw_food, "attribution")
    if (
        record_source_name != source_name
        or record_dataset_version != dataset_version
        or record_license != license_name
        or record_attribution != attribution
    ):
        raise ValueError("FOOD_SEED_METADATA_MISMATCH")
    definition = FoodDefinition(
        name=_required_text(raw_food, "name"),
        basis_type=raw_food.get("basis_type"),
        basis_amount=raw_food.get("basis_amount"),
        unit=raw_food.get("unit"),
        calories=raw_food.get("calories"),
        carbs=raw_food.get("carbs"),
        protein=raw_food.get("protein"),
        fat=raw_food.get("fat"),
        source="public",
    )
    aliases = _aliases(raw_food.get("aliases", []))
    provenance = raw_food.get("provenance", {})
    if not isinstance(provenance, dict):
        raise ValueError("FOOD_SEED_PROVENANCE_INVALID")
    record: dict[str, object] = {
        "source_name": record_source_name,
        "source_record_id": _required_text(raw_food, "source_record_id"),
        "dataset_version": record_dataset_version,
        "license": record_license,
        "attribution": record_attribution,
        "name": definition.name.strip(),
        "basis_type": definition.basis_type,
        "basis_amount": definition.basis_amount,
        "unit": definition.unit.strip(),
        "calories": definition.calories,
        "carbs": definition.carbs,
        "protein": definition.protein,
        "fat": definition.fat,
        "aliases": aliases,
        "provenance": provenance,
        "active": True,
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


def _insert_food(
    connection: sqlite3.Connection,
    food_id: str,
    record: dict[str, object],
) -> None:
    connection.execute(
        """
        INSERT INTO food_catalog (
            id, owner_user_id, source, source_name, source_record_id,
            dataset_version, name, basis_type, basis_amount, unit, calories,
            carbs, protein, fat, license, attribution, provenance_json,
            content_hash, active
        ) VALUES (
            ?, NULL, 'public', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1
        )
        """,
        _food_parameters(food_id, record),
    )


def _update_food(
    connection: sqlite3.Connection,
    food_id: str,
    record: dict[str, object],
) -> None:
    parameters = _food_parameters(food_id, record)
    connection.execute(
        """
        UPDATE food_catalog
        SET source_name = ?, source_record_id = ?, dataset_version = ?,
            name = ?, basis_type = ?, basis_amount = ?, unit = ?,
            calories = ?, carbs = ?, protein = ?, fat = ?, license = ?,
            attribution = ?, provenance_json = ?, content_hash = ?,
            active = 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (*parameters[1:], food_id),
    )


def _food_parameters(
    food_id: str,
    record: dict[str, object],
) -> tuple[object, ...]:
    return (
        food_id,
        record["source_name"],
        record["source_record_id"],
        record["dataset_version"],
        record["name"],
        record["basis_type"],
        record["basis_amount"],
        record["unit"],
        record["calories"],
        record["carbs"],
        record["protein"],
        record["fat"],
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


def _replace_aliases_and_search(
    connection: sqlite3.Connection,
    food_id: str,
    record: dict[str, object],
) -> None:
    aliases = record["aliases"]
    connection.execute("DELETE FROM catalog_aliases WHERE food_id = ?", (food_id,))
    connection.execute(
        """
        DELETE FROM catalog_search
        WHERE catalog_kind = 'food' AND catalog_id = ?
        """,
        (food_id,),
    )
    for alias in aliases:
        connection.execute(
            """
            INSERT INTO catalog_aliases (
                id, food_id, alias, normalized_alias, alias_kind
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                uuid5(
                    NAMESPACE_URL,
                    f"food-alias:{food_id}:{alias['kind']}:{alias['value']}",
                ).hex,
                food_id,
                alias["value"],
                _normalize(alias["value"]),
                alias["kind"],
            ),
        )
    connection.execute(
        """
        INSERT INTO catalog_search (
            catalog_kind, catalog_id, name, aliases, pinyin, source_tokens
        ) VALUES ('food', ?, ?, ?, ?, ?)
        """,
        (
            food_id,
            record["name"],
            " ".join(alias["value"] for alias in aliases),
            " ".join(
                alias["value"] for alias in aliases if alias["kind"] == "pinyin"
            ),
            _source_tokens(record),
        ),
    )


def _aliases(raw_aliases: object) -> tuple[dict[str, str], ...]:
    if not isinstance(raw_aliases, list):
        raise ValueError("FOOD_SEED_ALIASES_INVALID")
    aliases: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw_alias in raw_aliases:
        if not isinstance(raw_alias, str) or not raw_alias.strip():
            raise ValueError("FOOD_SEED_ALIAS_INVALID")
        value = raw_alias.strip()
        kind = "zh" if re.search(r"[\u3400-\u9fff]", value) else "alias"
        identity = (kind, _normalize(value))
        if identity not in seen:
            aliases.append({"value": value, "kind": kind})
            seen.add(identity)
    return tuple(aliases)


def _source_tokens(record: dict[str, object]) -> str:
    text = " ".join(
        (
            str(record["name"]),
            str(record["source_name"]),
            str(record["source_record_id"]),
            *(alias["value"] for alias in record["aliases"]),
        )
    )
    tokens = re.findall(
        r"[A-Za-z0-9_]+|[\u3400-\u9fff]+",
        unicodedata.normalize("NFKC", text),
    )
    expanded: list[str] = []
    for token in tokens:
        normalized = token.casefold()
        expanded.append(normalized)
        if re.fullmatch(r"[\u3400-\u9fff]+", normalized):
            expanded.extend(
                normalized[index : index + 2]
                for index in range(max(0, len(normalized) - 1))
            )
    return " ".join(dict.fromkeys(expanded))


def _required_text(value: object, key: str) -> str:
    if not isinstance(value, dict):
        raise ValueError("FOOD_SEED_OBJECT_INVALID")
    text = value.get(key)
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"FOOD_SEED_{key.upper()}_INVALID")
    return text.strip()


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()
