from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from backend.catalog_receiver.models import CatalogKind, ReceiverError, ReceiverIssue


LOCALIZATION_INVALID = "LOCALIZATION_INVALID"
LOCALIZATION_MISSING = "LOCALIZATION_MISSING"
LOCALIZATION_ORPHAN = "LOCALIZATION_ORPHAN"
LOCALIZATION_INSTRUCTION_COUNT_MISMATCH = "LOCALIZATION_INSTRUCTION_COUNT_MISMATCH"
LOCALIZATION_NAME_COLLISION = "LOCALIZATION_NAME_COLLISION"
LOCALIZATION_LATIN_UNAPPROVED = "LOCALIZATION_LATIN_UNAPPROVED"
LOCALIZATION_ALIAS_REDUNDANT = "LOCALIZATION_ALIAS_REDUNDANT"

FOOD_SOURCE_NAME = "Taiwan FDA Food Nutrient Database"
EXERCISE_SOURCE_NAME = "free-exercise-db"
LATIN_RUN = re.compile(r"[A-Za-z]+")


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FoodLocalizationEntry(_StrictFrozenModel):
    name_zh_cn: str
    aliases: tuple[str, ...] = ()
    review_note: str | None = None

    @field_validator("name_zh_cn")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _authored_text(value, field="name_zh_cn")

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _authored_text(value, field="aliases")
        return values

    @field_validator("review_note")
    @classmethod
    def validate_review_note(cls, value: str | None) -> str | None:
        if value is not None:
            _authored_text(value, field="review_note")
        return value


class ExerciseLocalizationEntry(_StrictFrozenModel):
    name_zh_cn: str
    aliases: tuple[str, ...] = ()
    instructions_zh_cn: tuple[str, ...]
    review_note: str | None = None

    @field_validator("name_zh_cn")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _authored_text(value, field="name_zh_cn")

    @field_validator("aliases", "instructions_zh_cn")
    @classmethod
    def validate_text_sequence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _authored_text(value, field="localized text")
        return values

    @field_validator("review_note")
    @classmethod
    def validate_review_note(cls, value: str | None) -> str | None:
        if value is not None:
            _authored_text(value, field="review_note")
        return value


class FoodLocalizationAsset(_StrictFrozenModel):
    schema_version: Literal[1]
    source_name: str
    locale: Literal["zh-CN"]
    entries: Mapping[str, FoodLocalizationEntry]

    @model_validator(mode="after")
    def freeze_entries(self) -> "FoodLocalizationAsset":
        object.__setattr__(self, "entries", _validated_mapping(self.entries, "entries"))
        return self


class ExerciseLocalizationAsset(_StrictFrozenModel):
    schema_version: Literal[1]
    source_name: str
    locale: Literal["zh-CN"]
    entries: Mapping[str, ExerciseLocalizationEntry]

    @model_validator(mode="after")
    def freeze_entries(self) -> "ExerciseLocalizationAsset":
        object.__setattr__(self, "entries", _validated_mapping(self.entries, "entries"))
        return self


class ExerciseTaxonomyAsset(_StrictFrozenModel):
    schema_version: Literal[1]
    source_name: str
    locale: Literal["zh-CN"]
    approved_latin: tuple[str, ...] = ()
    muscles: Mapping[str, str]
    equipment: Mapping[str, str]
    levels: Mapping[str, str]
    mechanics: Mapping[str, str]
    forces: Mapping[str, str]
    categories: Mapping[str, str]

    @field_validator("approved_latin")
    @classmethod
    def validate_approved_latin(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: set[str] = set()
        for value in values:
            _authored_text(value, field="approved_latin")
            if LATIN_RUN.fullmatch(unicodedata.normalize("NFKC", value)) is None:
                raise ValueError("approved_latin values must be Latin abbreviations")
            folded = _normalize(value)
            if folded in normalized:
                raise ValueError("approved_latin values must be unique after normalization")
            normalized.add(folded)
        return values

    @model_validator(mode="after")
    def freeze_taxonomy(self) -> "ExerciseTaxonomyAsset":
        for field in ("muscles", "equipment", "levels", "mechanics", "forces", "categories"):
            values = getattr(self, field)
            frozen = _validated_mapping(values, field, validate_values=True)
            object.__setattr__(self, field, frozen)
        return self


class LocalizationBundle(_StrictFrozenModel):
    catalog_kind: CatalogKind
    source_name: str
    food_entries: Mapping[str, FoodLocalizationEntry] = Field(default_factory=dict)
    exercise_entries: Mapping[str, ExerciseLocalizationEntry] = Field(default_factory=dict)
    taxonomy: ExerciseTaxonomyAsset | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "LocalizationBundle":
        if self.catalog_kind == "food":
            if self.exercise_entries or self.taxonomy is not None:
                raise ValueError("food bundles cannot contain exercise localization")
        elif self.food_entries:
            raise ValueError("exercise bundles cannot contain food localization")
        object.__setattr__(self, "food_entries", MappingProxyType(dict(self.food_entries)))
        object.__setattr__(self, "exercise_entries", MappingProxyType(dict(self.exercise_entries)))
        return self

    def food(self, source_id: str) -> FoodLocalizationEntry:
        entry = self.food_entries.get(source_id)
        if entry is None:
            raise _localization_error(
                LOCALIZATION_MISSING,
                f"Food localization is missing for source ID {source_id}.",
                record=source_id,
                source_path=self.source_name,
                field="source_record_id",
            )
        return entry

    def exercise(
        self,
        source_id: str,
        *,
        instruction_count: int,
    ) -> ExerciseLocalizationEntry:
        entry = self.exercise_entries.get(source_id)
        if entry is None:
            raise _localization_error(
                LOCALIZATION_MISSING,
                f"Exercise localization is missing for source ID {source_id}.",
                record=source_id,
                source_path=self.source_name,
                field="source_record_id",
            )
        actual = len(entry.instructions_zh_cn)
        if actual != instruction_count:
            raise _localization_error(
                LOCALIZATION_INSTRUCTION_COUNT_MISMATCH,
                f"Exercise localization for {source_id} has {actual} instructions; expected {instruction_count}.",
                record=source_id,
                source_path=self.source_name,
                field="instructions_zh_cn",
                observed=actual,
                expected=str(instruction_count),
            )
        return entry


def load_localization_bundle(
    *,
    catalog_kind: CatalogKind,
    localization_path: str | Path,
    taxonomy_path: str | Path | None = None,
) -> LocalizationBundle:
    localization_file = Path(localization_path)
    try:
        document = _freeze_json_arrays(_load_json(localization_file))
        if catalog_kind == "food":
            if taxonomy_path is not None:
                raise ValueError("food localization does not accept an exercise taxonomy")
            asset = FoodLocalizationAsset.model_validate(document, strict=True)
            _require_source_name(asset.source_name, FOOD_SOURCE_NAME)
            _validate_localized_entries(asset.entries, approved_latin=())
            return LocalizationBundle(
                catalog_kind="food",
                source_name=asset.source_name,
                food_entries=asset.entries,
            )
        if catalog_kind == "exercise":
            if taxonomy_path is None:
                raise ValueError("exercise localization requires a taxonomy asset")
            asset = ExerciseLocalizationAsset.model_validate(document, strict=True)
            taxonomy = ExerciseTaxonomyAsset.model_validate(
                _freeze_json_arrays(_load_json(Path(taxonomy_path))),
                strict=True,
            )
            _require_source_name(asset.source_name, EXERCISE_SOURCE_NAME)
            _require_source_name(taxonomy.source_name, EXERCISE_SOURCE_NAME)
            approved_latin = tuple(_normalize(value) for value in taxonomy.approved_latin)
            _validate_localized_entries(asset.entries, approved_latin=approved_latin)
            _validate_taxonomy_display(taxonomy, approved_latin=approved_latin)
            return LocalizationBundle(
                catalog_kind="exercise",
                source_name=asset.source_name,
                exercise_entries=asset.entries,
                taxonomy=taxonomy,
            )
        raise ValueError(f"unsupported catalog kind: {catalog_kind}")
    except ReceiverError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as error:
        raise ReceiverError(
            LOCALIZATION_INVALID,
            f"Localization asset is invalid: {localization_file.name}",
            exit_code=4,
        ) from error


def validate_localization_coverage(
    bundle: LocalizationBundle,
    source_ids: set[str],
) -> tuple[ReceiverIssue, ...]:
    localized_ids = (
        set(bundle.food_entries)
        if bundle.catalog_kind == "food"
        else set(bundle.exercise_entries)
    )
    issues: list[ReceiverIssue] = []
    for source_id in sorted(source_ids - localized_ids):
        issues.append(
            ReceiverIssue(
                severity="error",
                code=LOCALIZATION_MISSING,
                record=source_id,
                source_path=bundle.source_name,
                field="source_record_id",
                expected="one localization entry per source ID",
            )
        )
    for source_id in sorted(localized_ids - source_ids):
        issues.append(
            ReceiverIssue(
                severity="error",
                code=LOCALIZATION_ORPHAN,
                record=source_id,
                source_path=bundle.source_name,
                field="source_record_id",
                observed=source_id,
                expected="an existing source ID",
            )
        )
    return tuple(issues)


def _load_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8-sig"),
        object_pairs_hook=_pairs_without_duplicates,
    )


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _freeze_json_arrays(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_freeze_json_arrays(item) for item in value)
    if isinstance(value, dict):
        return {key: _freeze_json_arrays(item) for key, item in value.items()}
    return value


def _authored_text(value: str, *, field: str) -> str:
    if not value.strip():
        raise ValueError(f"{field} must not be blank")
    if value != value.strip():
        raise ValueError(f"{field} must not have leading or trailing whitespace")
    return value


def _validated_mapping(
    values: Mapping[str, Any],
    field: str,
    *,
    validate_values: bool = False,
) -> Mapping[str, Any]:
    for key, value in values.items():
        _authored_text(key, field=f"{field} key")
        if validate_values:
            _authored_text(value, field=f"{field} value")
    return MappingProxyType(dict(values))


def _require_source_name(observed: str, expected: str) -> None:
    if observed != expected:
        raise ValueError(f"source_name must be {expected!r}, got {observed!r}")


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _validate_localized_entries(
    entries: Mapping[str, FoodLocalizationEntry | ExerciseLocalizationEntry],
    *,
    approved_latin: tuple[str, ...],
) -> None:
    canonical_names: dict[str, str] = {}
    for source_id, entry in entries.items():
        normalized_name = _normalize(entry.name_zh_cn)
        colliding_id = canonical_names.get(normalized_name)
        if colliding_id is not None:
            raise _localization_error(
                LOCALIZATION_NAME_COLLISION,
                f"Source IDs {colliding_id} and {source_id} have the same canonical name.",
                record=source_id,
                field="name_zh_cn",
                observed=entry.name_zh_cn,
                expected="a unique canonical name after NFKC/casefold normalization",
            )
        canonical_names[normalized_name] = source_id

        normalized_aliases: set[str] = set()
        for alias in entry.aliases:
            normalized_alias = _normalize(alias)
            if normalized_alias == normalized_name or normalized_alias in normalized_aliases:
                raise _localization_error(
                    LOCALIZATION_ALIAS_REDUNDANT,
                    f"Localization alias is redundant for source ID {source_id}.",
                    record=source_id,
                    field="aliases",
                    observed=alias,
                    expected="aliases unique from the canonical name after NFKC/casefold normalization",
                )
            normalized_aliases.add(normalized_alias)

        _validate_latin(entry.name_zh_cn, source_id, "name_zh_cn", approved_latin)
        if isinstance(entry, ExerciseLocalizationEntry):
            for index, instruction in enumerate(entry.instructions_zh_cn):
                _validate_latin(
                    instruction,
                    source_id,
                    f"instructions_zh_cn[{index}]",
                    approved_latin,
                )


def _validate_taxonomy_display(
    taxonomy: ExerciseTaxonomyAsset,
    *,
    approved_latin: tuple[str, ...],
) -> None:
    for field in ("muscles", "equipment", "levels", "mechanics", "forces", "categories"):
        for source_value, localized_value in getattr(taxonomy, field).items():
            _validate_latin(localized_value, source_value, field, approved_latin)


def _validate_latin(
    value: str,
    record: str,
    field: str,
    approved_latin: tuple[str, ...],
) -> None:
    normalized_value = unicodedata.normalize("NFKC", value)
    approved = set(approved_latin)
    unapproved = [run for run in LATIN_RUN.findall(normalized_value) if _normalize(run) not in approved]
    if unapproved:
        raise _localization_error(
            LOCALIZATION_LATIN_UNAPPROVED,
            f"Localization display text contains unapproved Latin text: {', '.join(unapproved)}.",
            record=record,
            field=field,
            observed=value,
            expected="Chinese display text or an explicitly approved Latin abbreviation",
        )


def _localization_error(
    code: str,
    message: str,
    *,
    record: str | None = None,
    source_path: str | None = None,
    field: str | None = None,
    observed: Any = None,
    expected: str | None = None,
) -> ReceiverError:
    issue = ReceiverIssue(
        severity="error",
        code=code,
        record=record,
        source_path=source_path,
        field=field,
        observed=observed,
        expected=expected,
        message=message,
    )
    return ReceiverError(code, message, exit_code=4, issue=issue)


__all__ = [
    "ExerciseLocalizationAsset",
    "ExerciseLocalizationEntry",
    "ExerciseTaxonomyAsset",
    "FoodLocalizationAsset",
    "FoodLocalizationEntry",
    "LocalizationBundle",
    "load_localization_bundle",
    "validate_localization_coverage",
]
