"""Strict deterministic localization assets capped at 10,000,000 bytes per JSON file."""

from __future__ import annotations

import json
import unicodedata
from bisect import bisect_right
from pathlib import Path
from typing import Any, Literal, Mapping, TypeVar
from urllib.parse import SplitResult, urlsplit, urlunsplit

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
LOCALIZATION_JSON_SIZE_LIMIT = 10_000_000
ModelT = TypeVar("ModelT", bound=BaseModel)

# Unicode 15.1 Script=Latin ranges from https://www.unicode.org/Public/15.1.0/ucd/Scripts.txt.
LATIN_SCRIPT_RANGES = (
    (0x0041, 0x005A),
    (0x0061, 0x007A),
    (0x00AA, 0x00AA),
    (0x00BA, 0x00BA),
    (0x00C0, 0x00D6),
    (0x00D8, 0x00F6),
    (0x00F8, 0x01BA),
    (0x01BB, 0x01BB),
    (0x01BC, 0x01BF),
    (0x01C0, 0x01C3),
    (0x01C4, 0x0293),
    (0x0294, 0x0294),
    (0x0295, 0x02AF),
    (0x02B0, 0x02B8),
    (0x02E0, 0x02E4),
    (0x1D00, 0x1D25),
    (0x1D2C, 0x1D5C),
    (0x1D62, 0x1D65),
    (0x1D6B, 0x1D77),
    (0x1D79, 0x1D9A),
    (0x1D9B, 0x1DBE),
    (0x1E00, 0x1EFF),
    (0x2071, 0x2071),
    (0x207F, 0x207F),
    (0x2090, 0x209C),
    (0x212A, 0x212B),
    (0x2132, 0x2132),
    (0x214E, 0x214E),
    (0x2160, 0x2182),
    (0x2183, 0x2184),
    (0x2185, 0x2188),
    (0x2C60, 0x2C7B),
    (0x2C7C, 0x2C7D),
    (0x2C7E, 0x2C7F),
    (0xA722, 0xA76F),
    (0xA770, 0xA770),
    (0xA771, 0xA787),
    (0xA78B, 0xA78E),
    (0xA78F, 0xA78F),
    (0xA790, 0xA7CA),
    (0xA7D0, 0xA7D1),
    (0xA7D3, 0xA7D3),
    (0xA7D5, 0xA7D9),
    (0xA7F2, 0xA7F4),
    (0xA7F5, 0xA7F6),
    (0xA7F7, 0xA7F7),
    (0xA7F8, 0xA7F9),
    (0xA7FA, 0xA7FA),
    (0xA7FB, 0xA7FF),
    (0xAB30, 0xAB5A),
    (0xAB5C, 0xAB5F),
    (0xAB60, 0xAB64),
    (0xAB66, 0xAB68),
    (0xAB69, 0xAB69),
    (0xFB00, 0xFB06),
    (0xFF21, 0xFF3A),
    (0xFF41, 0xFF5A),
    (0x10780, 0x10785),
    (0x10787, 0x107B0),
    (0x107B2, 0x107BA),
    (0x1DF00, 0x1DF09),
    (0x1DF0A, 0x1DF0A),
    (0x1DF0B, 0x1DF1E),
    (0x1DF25, 0x1DF2A),
)
LATIN_SCRIPT_STARTS = tuple(start for start, _end in LATIN_SCRIPT_RANGES)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _FrozenDict(dict[str, Any]):
    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("localization mappings are immutable")

    __delitem__ = _immutable
    __ior__ = _immutable
    __setitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable

    def __copy__(self) -> "_FrozenDict":
        return self

    def __deepcopy__(self, _memo: dict[int, Any]) -> "_FrozenDict":
        return self

    def copy(self) -> "_FrozenDict":
        return self


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
    version: str
    source_name: str
    locale: Literal["zh-CN"]
    entries: Mapping[str, FoodLocalizationEntry]

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return _authored_text(value, field="version")

    @model_validator(mode="after")
    def freeze_entries(self) -> "FoodLocalizationAsset":
        object.__setattr__(self, "entries", _validated_mapping(self.entries, "entries"))
        return self


class ExerciseLocalizationAsset(_StrictFrozenModel):
    schema_version: Literal[1]
    version: str
    source_name: str
    locale: Literal["zh-CN"]
    entries: Mapping[str, ExerciseLocalizationEntry]

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return _authored_text(value, field="version")

    @model_validator(mode="after")
    def freeze_entries(self) -> "ExerciseLocalizationAsset":
        object.__setattr__(self, "entries", _validated_mapping(self.entries, "entries"))
        return self


class ExerciseTaxonomyAsset(_StrictFrozenModel):
    schema_version: Literal[1]
    version: str
    source_name: str
    locale: Literal["zh-CN"]
    approved_latin: tuple[str, ...] = ()
    muscles: Mapping[str, str]
    equipment: Mapping[str, str]
    levels: Mapping[str, str]
    mechanics: Mapping[str, str]
    forces: Mapping[str, str]
    categories: Mapping[str, str]

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return _authored_text(value, field="version")

    @field_validator("approved_latin")
    @classmethod
    def validate_approved_latin(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: set[str] = set()
        for value in values:
            _authored_text(value, field="approved_latin")
            folded = _normalize(value)
            if _latin_tokens(value) != (folded,):
                raise ValueError("approved_latin values must be Latin abbreviations")
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
    schema_version: Literal[1]
    version: str
    source_name: str
    locale: Literal["zh-CN"]
    localization_path: Path
    taxonomy_path: Path | None = None
    food_entries: Mapping[str, FoodLocalizationEntry] = Field(default_factory=_FrozenDict)
    exercise_entries: Mapping[str, ExerciseLocalizationEntry] = Field(default_factory=_FrozenDict)
    taxonomy: ExerciseTaxonomyAsset | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "LocalizationBundle":
        if self.catalog_kind == "food":
            if self.exercise_entries or self.taxonomy is not None or self.taxonomy_path is not None:
                raise ValueError("food bundles cannot contain exercise localization")
        elif self.food_entries or self.taxonomy is None or self.taxonomy_path is None:
            raise ValueError("exercise bundles require exercise localization and taxonomy metadata")
        object.__setattr__(self, "food_entries", _FrozenDict(self.food_entries))
        object.__setattr__(self, "exercise_entries", _FrozenDict(self.exercise_entries))
        return self

    def food(self, source_id: str) -> FoodLocalizationEntry:
        entry = self.food_entries.get(source_id)
        if entry is None:
            raise _localization_error(
                LOCALIZATION_MISSING,
                f"Food localization is missing for source ID {source_id}.",
                record=source_id,
                source_path=str(self.localization_path),
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
                source_path=str(self.localization_path),
                field="source_record_id",
            )
        actual = len(entry.instructions_zh_cn)
        if actual != instruction_count:
            raise _localization_error(
                LOCALIZATION_INSTRUCTION_COUNT_MISMATCH,
                f"Exercise localization for {source_id} has {actual} instructions; expected {instruction_count}.",
                record=source_id,
                source_path=str(self.localization_path),
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
    localization_file, document = _load_asset_document(localization_path, label="Localization")
    if catalog_kind == "food":
        if taxonomy_path is not None:
            raise _invalid_asset_error(
                "Localization",
                localization_file,
                "food localization does not accept an exercise taxonomy",
            )
        asset = _validate_asset_model(
            FoodLocalizationAsset,
            document,
            path=localization_file,
            label="Localization",
        )
        _require_source_name(
            asset.source_name,
            FOOD_SOURCE_NAME,
            path=localization_file,
            label="Localization",
        )
        _validate_localized_entries(
            asset.entries,
            approved_latin=(),
            source_path=localization_file,
        )
        return LocalizationBundle(
            catalog_kind="food",
            schema_version=asset.schema_version,
            version=asset.version,
            source_name=asset.source_name,
            locale=asset.locale,
            localization_path=localization_file,
            food_entries=asset.entries,
        )
    if catalog_kind == "exercise":
        asset = _validate_asset_model(
            ExerciseLocalizationAsset,
            document,
            path=localization_file,
            label="Localization",
        )
        _require_source_name(
            asset.source_name,
            EXERCISE_SOURCE_NAME,
            path=localization_file,
            label="Localization",
        )
        if taxonomy_path is None:
            raise _invalid_asset_error(
                "Taxonomy",
                None,
                "exercise localization requires a taxonomy asset",
            )
        taxonomy_file, taxonomy_document = _load_asset_document(taxonomy_path, label="Taxonomy")
        taxonomy = _validate_asset_model(
            ExerciseTaxonomyAsset,
            taxonomy_document,
            path=taxonomy_file,
            label="Taxonomy",
        )
        _require_source_name(
            taxonomy.source_name,
            EXERCISE_SOURCE_NAME,
            path=taxonomy_file,
            label="Taxonomy",
        )
        approved_latin = tuple(_normalize(value) for value in taxonomy.approved_latin)
        _validate_localized_entries(
            asset.entries,
            approved_latin=approved_latin,
            source_path=localization_file,
        )
        _validate_taxonomy_display(
            taxonomy,
            approved_latin=approved_latin,
            source_path=taxonomy_file,
        )
        return LocalizationBundle(
            catalog_kind="exercise",
            schema_version=asset.schema_version,
            version=asset.version,
            source_name=asset.source_name,
            locale=asset.locale,
            localization_path=localization_file,
            taxonomy_path=taxonomy_file,
            exercise_entries=asset.entries,
            taxonomy=taxonomy,
        )
    raise _invalid_asset_error(
        "Localization",
        localization_file,
        f"unsupported catalog kind: {catalog_kind}",
    )


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
                source_path=str(bundle.localization_path),
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
                source_path=str(bundle.localization_path),
                field="source_record_id",
                observed=source_id,
                expected="an existing source ID",
            )
        )
    return tuple(issues)


def _load_asset_document(path: str | Path, *, label: str) -> tuple[Path, Any]:
    raw_path = str(path)
    parsed = urlsplit(raw_path)
    is_windows_drive = len(parsed.scheme) == 1 and len(raw_path) > 1 and raw_path[1] == ":"
    if parsed.scheme and not is_windows_drive:
        sanitized = _sanitized_url(parsed)
        display_name = Path(parsed.path).name or "<remote>"
        raise _invalid_asset_error(
            label,
            None,
            "only local files are accepted; URLs are not supported",
            source_path=sanitized,
            display_name=display_name,
        )
    if raw_path.startswith(("\\\\", "//")):
        raise _invalid_asset_error(
            label,
            None,
            "only local files are accepted; UNC paths are not supported",
            source_path=raw_path,
            display_name=Path(raw_path).name or "<UNC>",
        )

    source_path = Path(path).expanduser().resolve(strict=False)
    try:
        stat = source_path.stat()
    except FileNotFoundError as error:
        raise _invalid_asset_error(label, source_path, "file not found") from error
    except OSError as error:
        raise _invalid_asset_error(label, source_path, "file metadata could not be read") from error
    if not source_path.is_file():
        raise _invalid_asset_error(label, source_path, "path must identify a regular file")
    if stat.st_size > LOCALIZATION_JSON_SIZE_LIMIT:
        reason = f"file exceeds the {LOCALIZATION_JSON_SIZE_LIMIT}-byte size limit"
        raise _invalid_asset_error(label, source_path, reason)
    try:
        text = source_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise _invalid_asset_error(label, source_path, "file must be valid UTF-8") from error
    except OSError as error:
        raise _invalid_asset_error(label, source_path, "file could not be read") from error
    try:
        document = json.loads(text, object_pairs_hook=_pairs_without_duplicates)
    except json.JSONDecodeError as error:
        reason = f"malformed JSON at line {error.lineno}, column {error.colno}"
        raise _invalid_asset_error(label, source_path, reason) from error
    except ValueError as error:
        raise _invalid_asset_error(label, source_path, str(error)) from error
    return source_path, _freeze_json_arrays(document)


def _sanitized_url(parsed: SplitResult) -> str:
    hostname = parsed.hostname or "<remote>"
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = f"{hostname}:{port}" if port is not None else hostname
    return urlunsplit((parsed.scheme.casefold(), netloc, parsed.path, "", ""))


def _validate_asset_model(
    model: type[ModelT],
    document: Any,
    *,
    path: Path,
    label: str,
) -> ModelT:
    try:
        return model.model_validate(document, strict=True)
    except ValidationError as error:
        raise _invalid_asset_error(label, path, "schema validation failed") from error


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
    return _FrozenDict(values)


def _require_source_name(
    observed: str,
    expected: str,
    *,
    path: Path,
    label: str,
) -> None:
    if observed != expected:
        reason = f"source_name must be {expected!r}, got {observed!r}"
        raise _invalid_asset_error(label, path, reason)


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _latin_tokens(value: str) -> tuple[str, ...]:
    tokens: list[str] = []
    current: list[str] = []
    pending_numbers: list[str] = []
    for character in value:
        category = unicodedata.category(character)
        if _is_latin_character(character):
            if not current:
                current.extend(pending_numbers)
                pending_numbers = []
            current.append(character)
        elif current and (category.startswith("M") or category.startswith("N")):
            current.append(character)
        elif not current and category.startswith("N"):
            pending_numbers.append(character)
        elif current:
            tokens.append(_normalize("".join(current)))
            current = []
            pending_numbers = []
        else:
            pending_numbers = []
    if current:
        tokens.append(_normalize("".join(current)))
    return tuple(tokens)


def _is_latin_character(character: str) -> bool:
    codepoint = ord(character)
    range_index = bisect_right(LATIN_SCRIPT_STARTS, codepoint) - 1
    if range_index >= 0 and codepoint <= LATIN_SCRIPT_RANGES[range_index][1]:
        return True
    normalized = _normalize(character)
    return bool(normalized) and all(_is_latin_codepoint(ord(item)) for item in normalized)


def _is_latin_codepoint(codepoint: int) -> bool:
    range_index = bisect_right(LATIN_SCRIPT_STARTS, codepoint) - 1
    return range_index >= 0 and codepoint <= LATIN_SCRIPT_RANGES[range_index][1]


def _validate_localized_entries(
    entries: Mapping[str, FoodLocalizationEntry | ExerciseLocalizationEntry],
    *,
    approved_latin: tuple[str, ...],
    source_path: Path,
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
                source_path=str(source_path),
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
                    source_path=str(source_path),
                    field="aliases",
                    observed=alias,
                    expected="aliases unique from the canonical name after NFKC/casefold normalization",
                )
            normalized_aliases.add(normalized_alias)

        _validate_latin(
            entry.name_zh_cn,
            source_id,
            "name_zh_cn",
            approved_latin,
            source_path=source_path,
        )
        if isinstance(entry, ExerciseLocalizationEntry):
            for index, instruction in enumerate(entry.instructions_zh_cn):
                _validate_latin(
                    instruction,
                    source_id,
                    f"instructions_zh_cn[{index}]",
                    approved_latin,
                    source_path=source_path,
                )


def _validate_taxonomy_display(
    taxonomy: ExerciseTaxonomyAsset,
    *,
    approved_latin: tuple[str, ...],
    source_path: Path,
) -> None:
    for field in ("muscles", "equipment", "levels", "mechanics", "forces", "categories"):
        for source_value, localized_value in getattr(taxonomy, field).items():
            _validate_latin(
                localized_value,
                source_value,
                field,
                approved_latin,
                source_path=source_path,
            )


def _validate_latin(
    value: str,
    record: str,
    field: str,
    approved_latin: tuple[str, ...],
    *,
    source_path: Path,
) -> None:
    approved = set(approved_latin)
    unapproved = [token for token in _latin_tokens(value) if token not in approved]
    if unapproved:
        raise _localization_error(
            LOCALIZATION_LATIN_UNAPPROVED,
            f"Localization display text contains unapproved Latin text: {', '.join(unapproved)}.",
            record=record,
            source_path=str(source_path),
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


def _invalid_asset_error(
    label: str,
    path: Path | None,
    reason: str,
    *,
    source_path: str | None = None,
    display_name: str | None = None,
) -> ReceiverError:
    name = display_name or (path.name if path is not None else "<missing>")
    message = f"{label} asset is invalid: {name} ({reason})."
    return _localization_error(
        LOCALIZATION_INVALID,
        message,
        source_path=source_path if source_path is not None else (str(path) if path is not None else None),
        expected="a valid local catalog localization asset",
    )


__all__ = [
    "ExerciseLocalizationAsset",
    "ExerciseLocalizationEntry",
    "ExerciseTaxonomyAsset",
    "FoodLocalizationAsset",
    "FoodLocalizationEntry",
    "LocalizationBundle",
    "LOCALIZATION_JSON_SIZE_LIMIT",
    "load_localization_bundle",
    "validate_localization_coverage",
]
