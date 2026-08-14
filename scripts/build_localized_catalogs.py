from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.catalog_receiver.localization import (
    LocalizationBundle,
    load_localization_bundle,
    validate_localization_coverage,
)
from backend.catalog_receiver.mapping import convert_tw2sp, load_mapping_profile
from backend.catalog_receiver.models import (
    CsvDialectInfo,
    CsvSource,
    JsonSource,
    MappingProfile,
    ProjectionResult,
    ReceiverError,
    SourceMetadata,
)
from backend.catalog_receiver.projectors import project_source
from backend.catalog_receiver.reporting import build_report
from backend.catalog_receiver.validators import validate_records


MAPPING_ROOT = PROJECT_ROOT / "backend" / "data" / "catalog" / "mappings"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build both bundled Mainland-localized catalogs deterministically."
    )
    parser.add_argument("--foods", type=Path, required=True)
    parser.add_argument("--food-localization", type=Path, required=True)
    parser.add_argument("--exercises", type=Path, required=True)
    parser.add_argument("--exercise-localization", type=Path, required=True)
    parser.add_argument("--exercise-taxonomy", type=Path, required=True)
    parser.add_argument("--food-output", type=Path, required=True)
    parser.add_argument("--exercise-output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _build_catalogs(args)
        return 0
    except ReceiverError as error:
        _print_error(error.code, error.message)
        return error.exit_code
    except Exception as error:
        _print_error("CATALOG_BUILD_FAILED", str(error))
        return 5


def _build_catalogs(args: argparse.Namespace) -> None:
    food_snapshot = _read_snapshot(args.foods, collection="foods")
    exercise_snapshot = _read_snapshot(args.exercises, collection="exercises")
    food_profile = load_mapping_profile(MAPPING_ROOT / "tfda-foods.v1.json")
    exercise_profile = load_mapping_profile(MAPPING_ROOT / "free-exercise-db.v1.json")
    food_bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=args.food_localization,
    )
    exercise_bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=args.exercise_localization,
        taxonomy_path=args.exercise_taxonomy,
    )

    food_source = _reconstruct_food_source(
        args.foods,
        food_snapshot,
        food_profile,
        food_bundle,
    )
    exercise_source = _reconstruct_exercise_source(
        args.exercises,
        exercise_snapshot,
    )
    food_projection = project_source(
        food_source,
        food_profile,
        localization_bundle=food_bundle,
    )
    exercise_projection = project_source(
        exercise_source,
        exercise_profile,
        localization_bundle=exercise_bundle,
    )
    _require_valid_projection(
        food_source.metadata,
        food_profile,
        food_projection,
        food_bundle,
        {record["source_record_id"] for record in food_snapshot["foods"]},
    )
    _require_valid_projection(
        exercise_source.metadata,
        exercise_profile,
        exercise_projection,
        exercise_bundle,
        {record["source_record_id"] for record in exercise_snapshot["exercises"]},
    )

    food_records = sorted(food_projection.records, key=lambda record: record.source_record_id)
    exercise_records = sorted(
        exercise_projection.records,
        key=lambda record: record.source_record_id,
    )
    food_payload = {
        "schema_version": 1,
        "source_name": food_profile.source_name,
        "dataset_version": food_profile.dataset_version,
        "license": food_profile.license,
        "attribution": food_profile.attribution,
        "foods": [record.model_dump(mode="json") for record in food_records],
    }
    exercise_payload = {
        "schema_version": 1,
        "dataset_version": exercise_profile.dataset_version,
        "managed_sources": [exercise_profile.source_name],
        "exercises": [record.model_dump(mode="json") for record in exercise_records],
    }
    food_text = _serialize_catalog(food_payload)
    exercise_text = _serialize_catalog(exercise_payload)
    _replace_catalog_pair(
        (args.food_output, food_text),
        (args.exercise_output, exercise_text),
    )


def _read_snapshot(path: Path, *, collection: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReceiverError(
            "CATALOG_SNAPSHOT_INVALID",
            f"Could not read normalized catalog snapshot {path}.",
            exit_code=4,
        ) from error
    if not isinstance(document, dict) or not isinstance(document.get(collection), list):
        raise ReceiverError(
            "CATALOG_SNAPSHOT_INVALID",
            f"Normalized catalog snapshot {path} must contain a {collection} array.",
            exit_code=4,
        )
    return document


def _reconstruct_food_source(
    path: Path,
    snapshot: dict[str, Any],
    profile: MappingProfile,
    bundle: LocalizationBundle,
) -> CsvSource:
    projection = profile.projection
    assert projection.pivot is not None
    selectors = {
        name: field.selector
        for name, field in projection.fields.items()
    }
    if any(selector is None for selector in selectors.values()):
        raise ReceiverError(
            "CATALOG_SNAPSHOT_INVALID",
            "The food mapping requires source selectors for snapshot reconstruction.",
            exit_code=4,
        )
    rows: list[dict[str, str]] = []
    nutrient_specs = (
        ("calories", "kcal"),
        ("carbs", "g"),
        ("protein", "g"),
        ("fat", "g"),
    )
    for record in snapshot["foods"]:
        source_id = _required_text(record, "source_record_id")
        upstream_name = _food_upstream_name(record)
        localized_aliases = (
            bundle.food(source_id).aliases
            if bundle.food(source_id) is not None
            else ()
        )
        common_name, english_name = _food_source_aliases(
            record.get("aliases"),
            upstream_name=upstream_name,
            localized_aliases=localized_aliases,
        )
        provenance = record.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        base = {
            selectors["source_record_id"]: source_id,
            selectors["name"]: upstream_name,
            selectors["traditional_name"]: upstream_name,
            selectors["common_name"]: common_name,
            selectors["english_name"]: english_name,
            selectors["food_category"]: str(provenance.get("food_category") or ""),
            selectors["description"]: str(provenance.get("description") or ""),
        }
        for nutrient, unit in nutrient_specs:
            if nutrient not in record:
                raise _upstream_missing(source_id, nutrient)
            row = dict(base)
            row[projection.pivot.key_selector] = projection.pivot.targets[nutrient][0]
            row[projection.pivot.unit_selector or ""] = unit
            row[projection.pivot.value_selector] = str(record[nutrient])
            rows.append(row)
    headers = tuple(dict.fromkeys(key for row in rows for key in row if key))
    return CsvSource(
        metadata=_source_metadata(path, kind="csv"),
        headers=headers,
        rows=tuple(rows),
        dialect=CsvDialectInfo(
            delimiter=",",
            quotechar='"',
            doublequote=True,
        ),
    )


def _food_upstream_name(record: dict[str, Any]) -> str:
    source_id = str(record.get("source_record_id") or "unknown")
    provenance = record.get("provenance")
    if isinstance(provenance, dict):
        localization = provenance.get("localization")
        if isinstance(localization, dict):
            upstream_name = localization.get("upstream_name")
            if isinstance(upstream_name, str) and upstream_name.strip():
                return upstream_name.strip()
    aliases = record.get("aliases")
    if isinstance(aliases, list):
        for alias in aliases:
            if isinstance(alias, str) and alias.strip() and _contains_han(alias):
                return alias.strip()
    raise _upstream_missing(
        source_id,
        "provenance.localization.upstream_name or Chinese source alias",
    )


def _food_source_aliases(
    aliases: Any,
    *,
    upstream_name: str,
    localized_aliases: Sequence[str],
) -> tuple[str, str]:
    if not isinstance(aliases, list):
        return "", ""
    ignored = {
        upstream_name.casefold(),
        convert_tw2sp(upstream_name).casefold(),
        *(alias.casefold() for alias in localized_aliases),
    }
    source_aliases = [
        alias.strip()
        for alias in aliases
        if isinstance(alias, str)
        and alias.strip()
        and alias.strip().casefold() not in ignored
    ]
    english_name = next(
        (
            alias
            for alias in reversed(source_aliases)
            if any(char.isascii() and char.isalpha() for char in alias)
        ),
        "",
    )
    common_name = next((alias for alias in source_aliases if alias != english_name), "")
    return common_name, english_name


def _reconstruct_exercise_source(
    path: Path,
    snapshot: dict[str, Any],
) -> JsonSource:
    upstream_records: list[dict[str, Any]] = []
    for record in snapshot["exercises"]:
        source_id = _required_text(record, "source_record_id")
        provenance = record.get("provenance")
        if not isinstance(provenance, dict):
            raise _upstream_missing(source_id, "provenance")
        upstream_name = provenance.get("upstream_name")
        if not isinstance(upstream_name, str) or not upstream_name.strip():
            raise _upstream_missing(source_id, "provenance.upstream_name")
        upstream = provenance.get("upstream")
        upstream = upstream if isinstance(upstream, dict) else {}
        instructions = upstream.get("instructions", provenance.get("instructions"))
        if not isinstance(instructions, list) or not all(
            isinstance(value, str) and value.strip() for value in instructions
        ):
            raise _upstream_missing(source_id, "upstream instructions")
        primary = upstream.get("primary_muscle", record.get("primary_muscle"))
        secondary = upstream.get("secondary_muscles", record.get("secondary_muscles"))
        image_count = provenance.get("image_count", 0)
        upstream_records.append(
            {
                "id": source_id,
                "name": upstream_name.strip(),
                "category": provenance.get("original_category"),
                "primaryMuscles": [primary] if isinstance(primary, str) else [],
                "secondaryMuscles": secondary if isinstance(secondary, list) else [],
                "equipment": upstream.get("equipment", provenance.get("equipment")),
                "level": upstream.get("level", provenance.get("level")),
                "mechanic": upstream.get("mechanic", provenance.get("mechanic")),
                "force": upstream.get("force", provenance.get("force")),
                "instructions": instructions,
                "images": ["preserved"] * image_count if isinstance(image_count, int) else [],
            }
        )
    return JsonSource(
        metadata=_source_metadata(path, kind="json"),
        document=upstream_records,
    )


def _require_valid_projection(
    source: SourceMetadata,
    profile: MappingProfile,
    projection: ProjectionResult,
    bundle: LocalizationBundle,
    source_ids: set[str],
) -> None:
    validation_issues = (
        *validate_records(projection.records),
        *validate_localization_coverage(bundle, source_ids),
    )
    report = build_report(
        source=source,
        profile=profile,
        projection=projection,
        validation_issues=validation_issues,
    )
    if report.has_errors:
        first = next(issue for issue in report.issues if issue.severity == "error")
        raise ReceiverError(
            "CATALOG_VALIDATION_FAILED",
            f"{profile.catalog_kind.title()} catalog validation failed: {first.code}.",
            exit_code=4,
            issue=first,
        )


def _serialize_catalog(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def _replace_catalog_pair(
    food: tuple[Path, str],
    exercise: tuple[Path, str],
) -> None:
    outputs = (Path(food[0]), Path(exercise[0]))
    if outputs[0].resolve() == outputs[1].resolve():
        raise ReceiverError(
            "CATALOG_OUTPUT_INVALID",
            "Food and exercise outputs must be different files.",
            exit_code=4,
        )
    for output in outputs:
        output.parent.mkdir(parents=True, exist_ok=True)
    run_id = uuid4().hex
    temporaries = tuple(
        output.with_name(f".{output.name}.{run_id}.tmp")
        for output in outputs
    )
    backups = tuple(
        output.with_name(f".{output.name}.{run_id}.bak")
        for output in outputs
    )
    existed = tuple(output.exists() for output in outputs)
    replaced = [False, False]
    unrecovered_backups: set[Path] = set()
    try:
        _write_fsynced(temporaries[0], food[1])
        _write_fsynced(temporaries[1], exercise[1])
        for output, backup, was_present in zip(outputs, backups, existed):
            if was_present:
                _copy_fsynced(output, backup)
        temporaries[0].replace(outputs[0])
        replaced[0] = True
        temporaries[1].replace(outputs[1])
        replaced[1] = True
    except Exception as replace_error:
        restore_failures: list[tuple[Path, Path, Exception]] = []
        for index in (1, 0):
            if not replaced[index]:
                continue
            if existed[index] and backups[index].exists():
                try:
                    backups[index].replace(outputs[index])
                except Exception as restore_error:
                    unrecovered_backups.add(backups[index])
                    restore_failures.append(
                        (outputs[index], backups[index], restore_error)
                    )
            elif outputs[index].exists():
                try:
                    outputs[index].unlink()
                except Exception as restore_error:
                    restore_failures.append(
                        (outputs[index], backups[index], restore_error)
                    )
        if restore_failures:
            details = "; ".join(
                f"output={output}, backup={backup}, error={error}"
                for output, backup, error in restore_failures
            )
            raise ReceiverError(
                "CATALOG_ROLLBACK_INCOMPLETE",
                f"Catalog replacement failed and rollback was incomplete: {details}",
                exit_code=5,
            ) from replace_error
        raise
    finally:
        for path in (*temporaries, *backups):
            if path not in unrecovered_backups:
                path.unlink(missing_ok=True)


def _write_fsynced(path: Path, value: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def _copy_fsynced(source: Path, destination: Path) -> None:
    with source.open("rb") as source_stream, destination.open("xb") as destination_stream:
        shutil.copyfileobj(source_stream, destination_stream)
        destination_stream.flush()
        os.fsync(destination_stream.fileno())


def _source_metadata(path: Path, *, kind: str) -> SourceMetadata:
    raw = path.read_bytes()
    stat = path.stat()
    return SourceMetadata(
        basename=path.name,
        kind=kind,
        size_bytes=len(raw),
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        sha256=hashlib.sha256(raw).hexdigest(),
        encoding="utf-8",
    )


def _required_text(record: dict[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _upstream_missing(str(record.get("source_record_id") or "unknown"), field)
    return value.strip()


def _upstream_missing(source_id: str, field: str) -> ReceiverError:
    return ReceiverError(
        "UPSTREAM_SOURCE_TEXT_MISSING",
        f"Catalog record {source_id} is missing preserved upstream source text: {field}.",
        exit_code=4,
    )


def _contains_han(value: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in value)


def _print_error(code: str, message: str) -> None:
    print(
        json.dumps(
            {"success": False, "error": {"code": code, "message": message}},
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
