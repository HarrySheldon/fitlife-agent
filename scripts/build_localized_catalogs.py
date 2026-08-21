from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Iterator, Sequence

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
FOOD_MAPPING_PROFILE = MAPPING_ROOT / "tfda-foods.v1.json"
EXERCISE_MAPPING_PROFILE = MAPPING_ROOT / "free-exercise-db.v1.json"
LEGACY_SEARCH_TERMS = (
    PROJECT_ROOT / "backend" / "data" / "catalog" / "legacy-search-terms.v1.json"
)


@dataclass(frozen=True)
class PublicationPaths:
    food_output: Path
    exercise_output: Path
    food_next: Path
    exercise_next: Path
    food_backup: Path
    exercise_backup: Path
    manifest: Path
    manifest_next: Path
    locks: tuple[Path, ...]

    @property
    def outputs(self) -> tuple[Path, Path]:
        return self.food_output, self.exercise_output

    @property
    def next_files(self) -> tuple[Path, Path]:
        return self.food_next, self.exercise_next

    @property
    def backups(self) -> tuple[Path, Path]:
        return self.food_backup, self.exercise_backup

    @classmethod
    def from_outputs(
        cls,
        food_output: Path,
        exercise_output: Path,
    ) -> PublicationPaths:
        food_output = food_output.resolve(strict=False)
        exercise_output = exercise_output.resolve(strict=False)
        lock_paths = {
            output.parent / ".catalog-localization.publish.lock"
            for output in (food_output, exercise_output)
        }
        manifest = food_output.parent / ".catalog-localization.publish.json"
        return cls(
            food_output=food_output,
            exercise_output=exercise_output,
            food_next=food_output.with_name(f".{food_output.name}.catalog.next"),
            exercise_next=exercise_output.with_name(
                f".{exercise_output.name}.catalog.next"
            ),
            food_backup=food_output.with_name(
                f".{food_output.name}.catalog.backup"
            ),
            exercise_backup=exercise_output.with_name(
                f".{exercise_output.name}.catalog.backup"
            ),
            manifest=manifest,
            manifest_next=manifest.with_name(f"{manifest.name}.next"),
            locks=tuple(
                sorted(lock_paths, key=lambda path: os.path.normcase(str(path)))
            ),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build both bundled Mainland-localized catalogs deterministically.",
        epilog=(
            "Windows recovery covers concurrent writers and process termination. "
            "File contents are fsynced, and parent directories are synced where the "
            "standard library supports it. Python's standard library does not guarantee "
            "directory-metadata ordering across Windows power loss or OS crashes."
        ),
    )
    parser.add_argument("--foods", type=Path, required=True)
    parser.add_argument("--food-localization", type=Path, required=True)
    parser.add_argument("--exercises", type=Path, required=True)
    parser.add_argument("--exercise-localization", type=Path, required=True)
    parser.add_argument("--exercise-taxonomy", type=Path, required=True)
    parser.add_argument(
        "--legacy-search-terms",
        type=Path,
        default=LEGACY_SEARCH_TERMS,
    )
    parser.add_argument("--food-output", type=Path, required=True)
    parser.add_argument("--exercise-output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    diagnostics: list[str] = []
    try:
        _build_catalogs(args, diagnostics)
        exit_code = 0
    except ReceiverError as error:
        _print_error(error.code, error.message)
        exit_code = error.exit_code
    except Exception as error:
        _print_error("CATALOG_BUILD_FAILED", str(error))
        exit_code = 5
    for diagnostic in diagnostics:
        _print_diagnostic(diagnostic, success=exit_code == 0)
    return exit_code


def _build_catalogs(args: argparse.Namespace, diagnostics: list[str]) -> None:
    paths = PublicationPaths.from_outputs(args.food_output, args.exercise_output)
    _validate_role_paths(args, paths)
    for output in paths.outputs:
        output.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_writer_locks(paths.locks, diagnostics):
        _recover_publication(paths, diagnostics)
        food_text, exercise_text = _render_catalogs(args)
        _publish_catalog_pair(paths, (food_text, exercise_text), diagnostics)


def _render_catalogs(args: argparse.Namespace) -> tuple[str, str]:
    food_snapshot = _read_snapshot(args.foods, collection="foods")
    exercise_snapshot = _read_snapshot(args.exercises, collection="exercises")
    food_profile = load_mapping_profile(FOOD_MAPPING_PROFILE)
    exercise_profile = load_mapping_profile(EXERCISE_MAPPING_PROFILE)
    food_bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=args.food_localization,
    )
    exercise_bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=args.exercise_localization,
        taxonomy_path=args.exercise_taxonomy,
    )
    legacy_search_terms = _load_legacy_search_terms(args.legacy_search_terms)

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
    food_projection = _merge_search_terms(
        food_projection,
        _snapshot_search_terms(food_snapshot, collection="foods"),
    )
    food_projection = _merge_search_terms(
        food_projection,
        legacy_search_terms["foods"],
    )
    exercise_projection = _merge_search_terms(
        exercise_projection,
        _snapshot_search_terms(exercise_snapshot, collection="exercises"),
    )
    exercise_projection = _merge_search_terms(
        exercise_projection,
        legacy_search_terms["exercises"],
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
    return food_text, exercise_text


def _validate_role_paths(
    args: argparse.Namespace,
    publication: PublicationPaths,
) -> None:
    roles = {
        "food input": Path(args.foods).resolve(strict=False),
        "exercise input": Path(args.exercises).resolve(strict=False),
        "food localization": Path(args.food_localization).resolve(strict=False),
        "exercise localization": Path(args.exercise_localization).resolve(strict=False),
        "exercise taxonomy": Path(args.exercise_taxonomy).resolve(strict=False),
        "legacy search terms": Path(args.legacy_search_terms).resolve(strict=False),
        "food mapping profile": FOOD_MAPPING_PROFILE.resolve(strict=False),
        "exercise mapping profile": EXERCISE_MAPPING_PROFILE.resolve(strict=False),
        "food output": publication.food_output,
        "exercise output": publication.exercise_output,
        "food next": publication.food_next,
        "exercise next": publication.exercise_next,
        "food backup": publication.food_backup,
        "exercise backup": publication.exercise_backup,
        "manifest": publication.manifest,
        "manifest next": publication.manifest_next,
    }
    for index, lock_path in enumerate(publication.locks, start=1):
        roles[f"lock {index}"] = lock_path
    allowed = {
        frozenset(("food input", "food output")),
        frozenset(("exercise input", "exercise output")),
    }
    for (left_role, left), (right_role, right) in combinations(roles.items(), 2):
        if frozenset((left_role, right_role)) in allowed:
            continue
        if _paths_alias(left, right):
            raise ReceiverError(
                "CATALOG_PATH_CONFLICT",
                f"Catalog path roles conflict: {left_role} and {right_role} resolve to {left}.",
                exit_code=4,
            )


def _paths_alias(left: Path, right: Path) -> bool:
    if left == right:
        return True
    try:
        return left.exists() and right.exists() and os.path.samefile(left, right)
    except OSError:
        return False


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


def _load_legacy_search_terms(path: Path) -> dict[str, dict[str, tuple[str, ...]]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReceiverError(
            "CATALOG_LEGACY_TERMS_INVALID",
            f"Could not read legacy catalog search terms {path}.",
            exit_code=4,
        ) from error
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise _invalid_legacy_search_terms(path)
    result: dict[str, dict[str, tuple[str, ...]]] = {}
    for collection in ("foods", "exercises"):
        entries = document.get(collection)
        if not isinstance(entries, dict):
            raise _invalid_legacy_search_terms(path)
        parsed: dict[str, tuple[str, ...]] = {}
        for source_id, terms in entries.items():
            if (
                not isinstance(source_id, str)
                or not source_id.strip()
                or not isinstance(terms, list)
                or not all(isinstance(term, str) and term.strip() for term in terms)
            ):
                raise _invalid_legacy_search_terms(path)
            parsed[source_id] = tuple(term.strip() for term in terms)
        result[collection] = parsed
    return result


def _invalid_legacy_search_terms(path: Path) -> ReceiverError:
    return ReceiverError(
        "CATALOG_LEGACY_TERMS_INVALID",
        f"Legacy catalog search terms {path} must use the version 1 schema.",
        exit_code=4,
    )


def _snapshot_search_terms(
    snapshot: dict[str, Any],
    *,
    collection: str,
) -> dict[str, tuple[str, ...]]:
    terms_by_source_id: dict[str, tuple[str, ...]] = {}
    for record in snapshot[collection]:
        source_id = _required_text(record, "source_record_id")
        canonical_name = _required_text(record, "name")
        aliases = record.get("aliases")
        if not isinstance(aliases, list) or not all(
            isinstance(alias, str) and alias.strip() for alias in aliases
        ):
            raise ReceiverError(
                "CATALOG_SNAPSHOT_INVALID",
                f"Snapshot record {source_id} must provide non-empty string aliases.",
                exit_code=4,
            )
        terms_by_source_id[source_id] = (
            canonical_name,
            *(alias.strip() for alias in aliases),
        )
    return terms_by_source_id


def _merge_search_terms(
    projection: ProjectionResult,
    terms_by_source_id: dict[str, tuple[str, ...]],
) -> ProjectionResult:
    records_by_source_id = {
        record.source_record_id: record for record in projection.records
    }
    unknown_ids = sorted(set(terms_by_source_id) - records_by_source_id.keys())
    if unknown_ids:
        raise ReceiverError(
            "CATALOG_LEGACY_TERMS_INVALID",
            f"Legacy search terms reference unknown source ID {unknown_ids[0]}.",
            exit_code=4,
        )
    records = []
    for record in projection.records:
        aliases = _deduplicated_aliases(
            record.name,
            (*record.aliases, *terms_by_source_id.get(record.source_record_id, ())),
        )
        records.append(record.model_copy(update={"aliases": aliases}))
    return projection.model_copy(update={"records": tuple(records)})


def _deduplicated_aliases(
    canonical_name: str,
    candidates: Sequence[str],
) -> tuple[str, ...]:
    seen = {_normalized_search_term(canonical_name)}
    aliases: list[str] = []
    for candidate in candidates:
        alias = candidate.strip()
        normalized = _normalized_search_term(alias)
        if not alias or normalized in seen:
            continue
        seen.add(normalized)
        aliases.append(alias)
    return tuple(aliases)


def _normalized_search_term(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


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
            isinstance(value, str) for value in instructions
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


@contextmanager
def _exclusive_writer_locks(
    paths: Sequence[Path],
    diagnostics: list[str] | None = None,
) -> Iterator[None]:
    diagnostics = diagnostics if diagnostics is not None else []
    streams: list[Any] = []
    try:
        for path in paths:
            stream = None
            try:
                stream = path.open("a+b")
                stream.seek(0, os.SEEK_END)
                if stream.tell() == 0:
                    stream.write(b"\0")
                    stream.flush()
                    os.fsync(stream.fileno())
                stream.seek(0)
                _lock_stream(stream)
            except OSError as error:
                if stream is not None and not stream.closed:
                    stream.close()
                raise ReceiverError(
                    "CATALOG_BUILD_LOCKED",
                    f"Another catalog build holds the writer lock: {path}.",
                    exit_code=5,
                ) from error
            streams.append(stream)
        yield
    finally:
        for stream in reversed(streams):
            try:
                try:
                    _unlock_stream(stream)
                except Exception as error:
                    diagnostics.append(
                        f"writer lock cleanup: path={Path(stream.name)}, error={error}"
                    )
            finally:
                try:
                    stream.close()
                except Exception as error:
                    diagnostics.append(
                        f"writer lock cleanup: path={Path(stream.name)}, error={error}"
                    )


def _lock_stream(stream: Any) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_stream(stream: Any) -> None:
    stream.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _publish_catalog_pair(
    paths: PublicationPaths,
    values: tuple[str, str],
    diagnostics: list[str],
) -> None:
    existed = tuple(output.exists() for output in paths.outputs)
    old_hashes = tuple(
        _file_hash(output) if present else None
        for output, present in zip(paths.outputs, existed)
    )
    new_hashes = tuple(_text_hash(value) for value in values)
    manifest = _publication_manifest(
        paths,
        "prepared",
        existed,
        old_hashes,
        new_hashes,
    )
    try:
        for next_file, value in zip(paths.next_files, values):
            _write_fsynced(next_file, value)
        for output, backup, present in zip(paths.outputs, paths.backups, existed):
            if present:
                _copy_fsynced(output, backup)
        _write_manifest(paths, manifest)
        _publication_checkpoint("prepared")

        paths.food_next.replace(paths.food_output)
        _fsync_parent(paths.food_output)
        _publication_checkpoint("food_output_replaced")
        manifest["phase"] = "food_replaced"
        _write_manifest(paths, manifest)
        _publication_checkpoint("food_replaced")

        paths.exercise_next.replace(paths.exercise_output)
        _fsync_parent(paths.exercise_output)
        _publication_checkpoint("exercise_output_replaced")
        manifest["phase"] = "both_replaced"
        _write_manifest(paths, manifest)
        _publication_checkpoint("both_replaced")

        manifest["phase"] = "committed"
        _write_manifest(paths, manifest)
        _publication_checkpoint("committed")
    except Exception:
        _recover_publication(paths, diagnostics)
        raise
    _cleanup_transaction(paths, diagnostics)


def _publication_checkpoint(_phase: str) -> None:
    pass


def _publication_manifest(
    paths: PublicationPaths,
    phase: str,
    existed: tuple[bool, bool],
    old_hashes: tuple[str | None, str | None],
    new_hashes: tuple[str, str],
) -> dict[str, Any]:
    entries: dict[str, Any] = {}
    for role, output, next_file, backup, present, old_hash, new_hash in zip(
        ("food", "exercise"),
        paths.outputs,
        paths.next_files,
        paths.backups,
        existed,
        old_hashes,
        new_hashes,
    ):
        entries[role] = {
            "output": str(output),
            "next": str(next_file),
            "backup": str(backup),
            "had_output": present,
            "old_sha256": old_hash,
            "new_sha256": new_hash,
        }
    return {"schema_version": 1, "phase": phase, **entries}


def _write_manifest(paths: PublicationPaths, manifest: dict[str, Any]) -> None:
    value = json.dumps(manifest, ensure_ascii=True, sort_keys=True) + "\n"
    _write_fsynced(paths.manifest_next, value)
    paths.manifest_next.replace(paths.manifest)
    _fsync_parent(paths.manifest)


def _recover_publication(paths: PublicationPaths, diagnostics: list[str]) -> None:
    if not paths.manifest.exists():
        _cleanup_paths(
            (*paths.next_files, *paths.backups, paths.manifest_next),
            diagnostics,
            context="stale publication staging",
        )
        return
    manifest = _read_manifest(paths)
    _validate_manifest(manifest, paths)
    output_hashes = _validate_recovery_output_hashes(manifest, paths)
    if manifest["phase"] == "committed":
        _cleanup_transaction(paths, diagnostics)
        return
    _validate_recovery_backups(manifest, paths, output_hashes)
    _restore_previous_generation(manifest, paths, output_hashes, diagnostics)


def _read_manifest(paths: PublicationPaths) -> dict[str, Any]:
    try:
        value = json.loads(paths.manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReceiverError(
            "CATALOG_RECOVERY_INVALID",
            f"Catalog recovery manifest is unreadable: {paths.manifest}.",
            exit_code=5,
        ) from error
    if not isinstance(value, dict):
        raise ReceiverError(
            "CATALOG_RECOVERY_INVALID",
            f"Catalog recovery manifest is invalid: {paths.manifest}.",
            exit_code=5,
        )
    return value


def _validate_manifest(manifest: dict[str, Any], paths: PublicationPaths) -> None:
    expected_paths = {
        "food": (paths.food_output, paths.food_next, paths.food_backup),
        "exercise": (
            paths.exercise_output,
            paths.exercise_next,
            paths.exercise_backup,
        ),
    }
    valid = (
        manifest.get("schema_version") == 1
        and manifest.get("phase")
        in {"prepared", "food_replaced", "both_replaced", "committed"}
    )
    for role, expected in expected_paths.items():
        entry = manifest.get(role)
        valid = valid and isinstance(entry, dict)
        if not isinstance(entry, dict):
            continue
        valid = valid and tuple(
            entry.get(field) for field in ("output", "next", "backup")
        ) == tuple(str(path) for path in expected)
        valid = valid and isinstance(entry.get("had_output"), bool)
        valid = valid and _valid_sha256(entry.get("new_sha256"))
        old_hash = entry.get("old_sha256")
        valid = valid and (
            _valid_sha256(old_hash)
            if entry.get("had_output")
            else old_hash is None
        )
    if not valid:
        raise ReceiverError(
            "CATALOG_RECOVERY_INVALID",
            f"Catalog recovery manifest does not match the requested outputs: {paths.manifest}.",
            exit_code=5,
        )


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _validate_recovery_output_hashes(
    manifest: dict[str, Any],
    paths: PublicationPaths,
) -> dict[str, str | None]:
    phase = manifest["phase"]
    observed: dict[str, str | None] = {}
    conflicts: list[str] = []
    for role, output in zip(("food", "exercise"), paths.outputs):
        entry = manifest[role]
        current_hash = _recovery_file_hash(output, paths, phase)
        observed[role] = current_hash
        allowed_hashes = _allowed_recovery_hashes(
            phase,
            role,
            entry["old_sha256"],
            entry["new_sha256"],
        )
        if current_hash not in allowed_hashes:
            conflicts.append(
                f"role={role}, output={output}, observed={current_hash or 'missing'}"
            )
    if conflicts:
        raise _recovery_conflict(paths, phase, conflicts)
    return observed


def _allowed_recovery_hashes(
    phase: str,
    role: str,
    old_hash: str | None,
    new_hash: str,
) -> tuple[str | None, ...]:
    if phase == "committed":
        return (new_hash,)
    if phase == "prepared" and role == "exercise":
        return (old_hash,)
    # Replacement may precede its phase write, and an interrupted rollback may
    # already have restored either output.
    return tuple(dict.fromkeys((old_hash, new_hash)))


def _validate_recovery_backups(
    manifest: dict[str, Any],
    paths: PublicationPaths,
    output_hashes: dict[str, str | None],
) -> None:
    conflicts: list[str] = []
    for role, backup in zip(("food", "exercise"), paths.backups):
        entry = manifest[role]
        if not entry["had_output"] or output_hashes[role] == entry["old_sha256"]:
            continue
        backup_hash = _recovery_file_hash(backup, paths, manifest["phase"])
        if backup_hash != entry["old_sha256"]:
            conflicts.append(
                f"role={role}, backup={backup}, observed={backup_hash or 'missing'}"
            )
    if conflicts:
        raise _recovery_conflict(paths, manifest["phase"], conflicts)


def _recovery_file_hash(
    path: Path,
    paths: PublicationPaths,
    phase: str,
) -> str | None:
    try:
        path.stat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise _recovery_conflict(
            paths,
            phase,
            [f"path={path}, observed=unreadable"],
        ) from error
    try:
        return _file_hash(path)
    except OSError as error:
        raise _recovery_conflict(
            paths,
            phase,
            [f"path={path}, observed=unreadable"],
        ) from error


def _recovery_conflict(
    paths: PublicationPaths,
    phase: str,
    conflicts: Sequence[str],
) -> ReceiverError:
    return ReceiverError(
        "CATALOG_RECOVERY_CONFLICT",
        f"Catalog recovery state conflicts with phase {phase} in {paths.manifest}: "
        + "; ".join(conflicts),
        exit_code=5,
    )


def _restore_previous_generation(
    manifest: dict[str, Any],
    paths: PublicationPaths,
    output_hashes: dict[str, str | None],
    diagnostics: list[str],
) -> None:
    failures: list[str] = []
    for role, output, backup in zip(
        ("food", "exercise"), paths.outputs, paths.backups
    ):
        entry = manifest[role]
        try:
            if entry["had_output"]:
                if output_hashes[role] == entry["old_sha256"]:
                    continue
                backup.replace(output)
                _fsync_parent(output)
            elif output_hashes[role] == entry["new_sha256"]:
                output.unlink()
                _fsync_parent(output)
        except Exception as error:
            failures.append(f"output={output}, backup={backup}, error={error}")
    if failures:
        _cleanup_paths(
            (*paths.next_files, paths.manifest_next),
            diagnostics,
            context="incomplete rollback staging",
        )
        raise ReceiverError(
            "CATALOG_ROLLBACK_INCOMPLETE",
            "Catalog rollback was incomplete; recovery data was retained: "
            + "; ".join(failures),
            exit_code=5,
        )
    _cleanup_transaction(paths, diagnostics)


def _cleanup_transaction(paths: PublicationPaths, diagnostics: list[str]) -> None:
    before = len(diagnostics)
    _cleanup_paths(
        (*paths.next_files, *paths.backups, paths.manifest_next),
        diagnostics,
        context="publication cleanup",
    )
    if len(diagnostics) == before:
        _cleanup_paths(
            (paths.manifest,),
            diagnostics,
            context="publication cleanup",
        )


def _cleanup_paths(
    paths: Sequence[Path],
    diagnostics: list[str],
    *,
    context: str,
) -> None:
    for path in dict.fromkeys(paths):
        try:
            path.unlink(missing_ok=True)
            _fsync_parent(path)
        except Exception as error:
            diagnostics.append(f"{context}: path={path}, error={error}")


def _write_fsynced(path: Path, value: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_parent(path)


def _copy_fsynced(source: Path, destination: Path) -> None:
    with (
        source.open("rb") as source_stream,
        destination.open("xb") as destination_stream,
    ):
        shutil.copyfileobj(source_stream, destination_stream)
        destination_stream.flush()
        os.fsync(destination_stream.fileno())
    _fsync_parent(destination)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fsync_parent(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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


def _print_diagnostic(message: str, *, success: bool) -> None:
    print(
        json.dumps(
            {
                "success": success,
                "diagnostic": {
                    "code": "CATALOG_CLEANUP_FAILED",
                    "message": message,
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
