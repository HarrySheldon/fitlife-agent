from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SourceKind = Literal["csv", "json"]
CatalogKind = Literal["food", "exercise"]
Severity = Literal["info", "warning", "error"]


class ReceiverIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Severity
    code: str
    record: int | str | None = None
    source_path: str | None = None
    field: str | None = None
    observed: Any = None
    expected: str | None = None
    suggestion: str | None = None
    message: str | None = None


class ReceiverError(Exception):
    """A coded receiver failure suitable for CLI exit-code translation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        exit_code: int = 2,
        issue: ReceiverIssue | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.issue = issue


class SourceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    basename: str
    kind: SourceKind
    size_bytes: int = Field(ge=0)
    modified_at: datetime
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    encoding: str


class CsvDialectInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delimiter: str
    quotechar: str
    doublequote: bool
    escapechar: str | None = None
    lineterminator: str = "\n"


class CsvSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: SourceMetadata
    headers: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    dialect: CsvDialectInfo


class JsonSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: SourceMetadata
    document: Any


SourceDocument = CsvSource | JsonSource


TransformOperation = Literal[
    "strip",
    "number",
    "first",
    "list",
    "constant",
    "enum_map",
    "opencc_t2s",
    "lower",
]


class TransformSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: TransformOperation
    value: Any = None
    values: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_parameters(self) -> "TransformSpec":
        if self.operation == "enum_map" and self.values is None:
            raise ValueError("enum_map requires values")
        if self.operation != "enum_map" and self.values is not None:
            raise ValueError("values is only valid for enum_map")
        if self.operation != "constant" and self.value is not None:
            raise ValueError("value is only valid for constant")
        return self


class FieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selector: str | None = None
    constant: Any = None
    transforms: tuple[TransformSpec, ...] = ()

    @model_validator(mode="after")
    def validate_source(self) -> "FieldSpec":
        has_constant = self.constant is not None
        if (self.selector is None) == (not has_constant):
            raise ValueError("exactly one of selector or constant is required")
        return self


class PivotSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_selector: str
    value_selector: str
    unit_selector: str | None = None
    targets: dict[str, tuple[str, ...]]


class EnrichmentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_field: str
    minimum_coverage: float = Field(default=0, ge=0, le=1)


class ProjectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Literal["row", "grouped_pivot"]
    record_selector: str | None = None
    grouping_key: str | None = None
    fields: dict[str, FieldSpec]
    pivot: PivotSpec | None = None
    category_map: dict[str, str] = Field(default_factory=dict)
    excluded_categories: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_strategy(self) -> "ProjectionSpec":
        if self.strategy == "grouped_pivot":
            if not self.grouping_key or self.pivot is None:
                raise ValueError("grouped_pivot requires grouping_key and pivot")
        elif self.grouping_key is not None or self.pivot is not None:
            raise ValueError("row projection cannot configure grouping or pivot")
        return self


class MappingProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    profile_name: str = Field(min_length=1)
    profile_version: str = Field(min_length=1)
    catalog_kind: CatalogKind
    input_format: SourceKind
    source_name: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    license: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    projection: ProjectionSpec
    enrichment: EnrichmentSpec | None = None
    retired_sources: tuple[str, ...] = ()


class FieldDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    types: tuple[str, ...]
    samples: tuple[Any, ...]


class StructureInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: SourceMetadata
    row_count: int | None = None
    headers: tuple[str, ...] = ()
    array_paths: tuple[str, ...] = ()
    candidate_record_arrays: tuple[str, ...] = ()
    fields: tuple[FieldDescription, ...] = ()
    mapping_candidates: dict[str, str] = Field(default_factory=dict)
    ambiguous_fields: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()
    draft_profile: dict[str, Any]
