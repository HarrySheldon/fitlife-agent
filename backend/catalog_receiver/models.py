from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
