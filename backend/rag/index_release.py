"""Index releases: validity by manifest, publication by atomic PostgreSQL pointer swap."""
from __future__ import annotations

from typing import Callable

from backend.infrastructure.postgres.database import PostgresDatabase
from backend.infrastructure.postgres.runtime import get_database
from backend.rag.contracts import (
    CHUNKING_VERSION,
    IndexManifest,
    content_hash,
    corpus_digest,
)
from backend.rag.pgvector_store import (
    PgVectorReleaseStore,
    _config_digest_for,
    _provider_identity,
    _validate_vector,
)

EmbeddingLookup = Callable[[str], list[float]]


def _config_digest(provider) -> str:
    provider_name, model_name = _provider_identity(provider)
    return _config_digest_for(provider_name, model_name, provider.dimensions)


def index_is_valid(
    manifest: IndexManifest,
    *,
    provider,
    documents: list[dict],
    chunk_count: int,
) -> bool:
    """Is this manifest still a correct description of the index we would build now?"""
    provider_name, model_name = _provider_identity(provider)
    return (
        manifest.corpus_digest == corpus_digest(documents)
        and manifest.chunking_version == CHUNKING_VERSION
        and manifest.embedding_provider == provider_name
        and manifest.embedding_model == model_name
        and manifest.embedding_dimensions == provider.dimensions
        and manifest.chunk_count == chunk_count
    )


def _store(database: PostgresDatabase | None = None) -> PgVectorReleaseStore:
    return PgVectorReleaseStore(database or get_database())


def read_manifest(database: PostgresDatabase | None = None) -> IndexManifest | None:
    """The active manifest, or ``None`` when nothing has been published yet."""
    return _store(database).read_manifest()


def publish_release(
    *,
    chunks: list[dict],
    provider,
    embedding_lookup: EmbeddingLookup,
    documents: list[dict],
    database: PostgresDatabase | None = None,
    release_id: str | None = None,
    previous_release_id: str | None = None,
    keep_previous: int = 1,
) -> str:
    """Build, validate and atomically activate a PostgreSQL pgvector release."""
    return _store(database).publish_release(
        chunks=chunks,
        provider=provider,
        embedding_lookup=embedding_lookup,
        documents=documents,
        release_id=release_id,
        previous_release_id=previous_release_id,
        keep_previous=keep_previous,
    )


def load_release(
    database: PostgresDatabase | None = None,
) -> tuple[IndexManifest, list[dict]] | None:
    """The active release's manifest and chunk list, or ``None``."""
    store = _store(database)
    manifest = store.read_manifest()
    if manifest is None:
        return None
    chunks = store.load_chunks(manifest.release_id)
    return manifest, chunks


__all__ = [
    "EmbeddingLookup",
    "_config_digest",
    "_provider_identity",
    "_validate_vector",
    "index_is_valid",
    "load_release",
    "publish_release",
    "read_manifest",
]
