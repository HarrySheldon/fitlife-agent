"""Contracts for knowledge governance, retrieval and evidence.

These types exist so a retrieval result can say *what it is* rather than only returning
a bare list. The distinction that matters most is between three outcomes that the
current implementation collapses into one:

* ``ok`` - matching chunks were found for this query in this release;
* ``insufficient`` - the corpus was searchable but has no support for this query;
* ``unavailable`` - no search could be performed at all.

Returning the nearest few chunks when nothing matched is the failure this contract is
designed to make impossible to express accidentally.

Nothing here reads a file, a network or a credential. It only defines shapes.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Bumping this changes every chunk_id, so it must be recorded in the manifest: a
# different splitter is a different corpus, not the same corpus chunked differently.
CHUNKING_VERSION = "markdown-heading-v2"
MANIFEST_SCHEMA_VERSION = 1

RetrievalStatus = Literal["ok", "insufficient", "unavailable"]
RetrievalMode = Literal["vector", "lexical", "hybrid", "reranked"]

_DIGEST = r"^[a-f0-9]{64}$"
_ID = r"^chunk-[a-f0-9]{16,64}$"


def content_hash(text: str) -> str:
    """Hash the chunk body only; formatting around it is not the content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_id(source: str, heading: str, ordinal: int) -> str:
    """A stable id for a position in a document.

    Position, not content: the id must stay the same when the text at that position
    changes, so that a content change is detectable by comparing hashes rather than by
    noticing that every id moved.
    """
    material = f"{source}\n{heading}\n{ordinal}".encode("utf-8")
    return "chunk-" + hashlib.sha256(material).hexdigest()[:32]


def document_version(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Chunk(BaseModel):
    """One retrievable unit, carrying enough identity to be cited and invalidated."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str = Field(pattern=_ID)
    content_hash: str = Field(pattern=_DIGEST)
    document_version: str = Field(pattern=_DIGEST)
    source: str = Field(min_length=1)
    heading: str = Field(min_length=1)
    text: str = Field(min_length=1)
    ordinal: int = Field(ge=0)

    @model_validator(mode="after")
    def hash_matches_text(self):
        if self.content_hash != content_hash(self.text):
            raise ValueError("chunk content_hash does not match its text")
        return self


class IndexManifest(BaseModel):
    """What an index release was built from.

    A manifest answers "can this index still be trusted for this corpus?" without
    loading the index. Comparing only a model name and a chunk count is what allowed a
    same-length content edit to keep serving the old text.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    release_id: str = Field(min_length=8, max_length=64)
    corpus_digest: str = Field(pattern=_DIGEST)
    chunking_version: str = Field(min_length=1)
    embedding_provider: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    embedding_dimensions: int = Field(gt=0)
    config_digest: str = Field(pattern=_DIGEST)
    chunk_count: int = Field(ge=0)


class Hit(BaseModel):
    """A retrieved chunk plus why it is here. Never a bare score."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str = Field(pattern=_ID)
    content_hash: str = Field(pattern=_DIGEST)
    source: str = Field(min_length=1)
    heading: str = Field(min_length=1)
    text: str = Field(min_length=1)
    # Rank and fused score are ordering facts, not a semantic confidence claim.
    rank: int = Field(ge=1)
    score: float | None = None


class RetrievalResult(BaseModel):
    """The detailed answer the tool returns.

    ``fallback_reason`` is mandatory whenever the outcome is not a plain vector hit, so
    "we fell back to keyword matching" and "we had nothing" stop looking identical.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: RetrievalStatus
    hits: list[Hit] = Field(default_factory=list, max_length=100)
    release_id: str | None = None
    retrieval_mode: RetrievalMode | None = None
    fallback_reason: str | None = None

    @model_validator(mode="after")
    def status_and_hits_agree(self):
        if self.status == "ok" and not self.hits:
            raise ValueError("status 'ok' requires at least one hit")
        if self.status != "ok" and self.hits:
            # A non-ok status that still carries text is exactly how an unrelated
            # answer gets presented as if it were supported.
            raise ValueError("a non-ok status must not carry hits")
        if self.status != "ok" and self.retrieval_mode is not None:
            raise ValueError("a non-ok status has no successful retrieval mode")
        return self

    @classmethod
    def insufficient(cls, *, release_id: str | None = None,
                     fallback_reason: str = "no_matching_chunk") -> "RetrievalResult":
        return cls(status="insufficient", release_id=release_id,
                   fallback_reason=fallback_reason)

    @classmethod
    def unavailable(cls, *, reason: str) -> "RetrievalResult":
        return cls(status="unavailable", fallback_reason=reason)

    @classmethod
    def found(cls, *, hits: list[Hit], release_id: str,
              retrieval_mode: RetrievalMode = "vector",
              fallback_reason: str | None = None) -> "RetrievalResult":
        return cls(status="ok", hits=hits, release_id=release_id,
                   retrieval_mode=retrieval_mode, fallback_reason=fallback_reason)


def locator(source: str, heading: str) -> str:
    """A human-readable, content-independent locator for a chunk position.

    Fixtures refer to chunks by locator rather than by hash so a reviewer can read the
    corpus and see which evidence is meant. The test resolves a locator to the chunk
    that currently occupies that position.
    """
    return f"{source}#{heading}"


_LOCATOR = r"^[^#]+#[^#]+$"


class QueryCase(BaseModel):
    """One labelled query in the evaluation corpus.

    ``split`` is recorded so a development case can never be quietly reported as a
    held-out result, and ``allowed_points`` is what a faithful answer may say - not the
    text a model must reproduce.

    ``relevant_chunk_ids`` holds locators (``source#heading``) in this schema version:
    readable in review, resolved to chunk ids at run time.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    corpus_version: str = Field(min_length=1)
    query: str = Field(min_length=1)
    language: Literal["zh-CN", "en-US"] = "zh-CN"
    split: Literal["dev", "holdout"]
    relevant_chunk_ids: list[str] = Field(default_factory=list)
    allowed_points: list[str] = Field(default_factory=list)
    should_clarify: bool = False
    should_refuse: bool = False
    notes: str | None = None

    @model_validator(mode="after")
    def locators_are_locators(self):
        for value in self.relevant_chunk_ids:
            if not re.fullmatch(_LOCATOR, value):
                raise ValueError(
                    f"relevant_chunk_ids entry {value!r} is not a source#heading locator")
        return self

    @model_validator(mode="after")
    def a_refusal_is_not_also_supported(self):
        if self.should_refuse and self.relevant_chunk_ids:
            raise ValueError("a refusal case must not declare relevant chunks")
        if self.should_refuse and self.should_clarify:
            # Refusing and needing clarification are different answers; a case that
            # claims both cannot be scored against either.
            raise ValueError("a case cannot both refuse and require clarification")
        if not self.should_refuse and not self.should_clarify and not self.relevant_chunk_ids:
            # A plain supported case must say which chunks support it, otherwise
            # "faithful answer" has nothing to be faithful to.
            raise ValueError("a supported case must declare its relevant chunks")
        return self


class RetrievalCorpus(BaseModel):
    """A fixed synthetic corpus. No private data, no live fetch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    documents: list[dict[str, Any]] = Field(min_length=1)
    cases: list[QueryCase] = Field(min_length=1)

    @model_validator(mode="after")
    def every_case_of_this_corpus(self):
        for case in self.cases:
            if case.corpus_version != self.version:
                raise ValueError(
                    f"case {case.case_id} declares corpus_version {case.corpus_version}, "
                    f"but the corpus is {self.version}")
        return self

    @model_validator(mode="after")
    def ids_are_unique(self):
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("query case ids must be unique")
        return self


def corpus_digest(documents: list[dict[str, Any]]) -> str:
    """Digest the normalised corpus, not its file layout."""
    material = []
    for document in documents:
        source = str(document.get("source", ""))
        text = str(document.get("text", ""))
        material.append(f"{source}\u0000{text}")
    joined = "\u0001".join(sorted(material))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


_WHITESPACE = re.compile(r"[ \t\u3000]+")


def normalise_text(text: str) -> str:
    """Collapse horizontal whitespace but keep line structure.

    Line structure carries meaning in a markdown corpus: collapsing newlines would make
    two genuinely different documents share a digest.
    """
    return "\n".join(_WHITESPACE.sub(" ", line).strip() for line in text.splitlines())
