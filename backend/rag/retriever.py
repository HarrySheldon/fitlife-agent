from __future__ import annotations

import time

from backend.agent.telemetry import SafeTelemetryContext, active_telemetry_context
from backend.config import get_settings
from backend.infrastructure.postgres.database import PostgresDatabase
from backend.infrastructure.postgres.runtime import get_database
from backend.rag.contracts import Hit, IndexManifest, RetrievalResult
from backend.rag.index_release import index_is_valid, load_release, publish_release, read_manifest
from backend.rag.ingest import ensure_chunk_identity, load_knowledge_chunks
from backend.rag.pgvector_store import PgVectorReleaseStore
from backend.rag.ranking import fuse, rerank, select_with_diversity
from backend.rag.vector_store import (
    EmbeddingProvider,
    build_embedding_provider,
    score_text,
    tokenize,
)


class _IndexStaleError(RuntimeError):
    """Raised when request-path retrieval finds no valid release and building is disabled."""


_INDEX_CACHE: dict[tuple[str, str, str], tuple[IndexManifest, list[dict]]] = {}


def clear_index_cache() -> None:
    """Clear the in-process loaded index cache (primarily for tests)."""
    _INDEX_CACHE.clear()


def _resolve_database(database: PostgresDatabase | None) -> PostgresDatabase:
    return database if database is not None else get_database()


def build_knowledge_index(
    *,
    provider: EmbeddingProvider | None = None,
    database: PostgresDatabase | None = None,
) -> str:
    """Ensure an up-to-date release is published in PostgreSQL and warm the cache."""
    chunks = ensure_chunk_identity(load_knowledge_chunks())
    provider = provider or build_embedding_provider()
    db = _resolve_database(database)
    manifest, _ = _load_or_build_release(chunks, provider=provider, database=db, allow_build=True)
    return manifest.release_id


def retrieve_knowledge(
    query: str,
    top_k: int = 3,
    *,
    provider: EmbeddingProvider | None = None,
    database: PostgresDatabase | None = None,
) -> list[dict]:
    """Compatibility entry: just the hits, returning plain dicts."""
    result = retrieve_detailed(query, top_k, provider=provider, database=database)
    return [
        {
            "chunk_id": hit.chunk_id,
            "content_hash": hit.content_hash,
            "source": hit.source,
            "heading": hit.heading,
            "text": hit.text,
            "rank": hit.rank,
            "score": hit.score if hit.score is not None else 0.0,
        }
        for hit in result.hits
    ]


def retrieve_detailed(
    query: str,
    top_k: int = 3,
    *,
    provider: EmbeddingProvider | None = None,
    database: PostgresDatabase | None = None,
    reranker=None,
    per_source_cap: int = 2,
    allow_build: bool | None = None,
    telemetry=None,
) -> RetrievalResult:
    """The full answer: status, hits, release, mode and why it fell back."""
    tel = SafeTelemetryContext(telemetry) if telemetry is not None else SafeTelemetryContext(active_telemetry_context())
    started = time.monotonic()
    chunks = ensure_chunk_identity(load_knowledge_chunks())
    provider = provider or build_embedding_provider()
    settings = get_settings()
    db = _resolve_database(database)
    effective_allow_build = settings.rag_allow_request_build if allow_build is None else allow_build

    with tel.sync_span("fitlife.rag.retrieve", {"provider": str(getattr(provider, "provider_name", "unknown")), "model": str(getattr(provider, "model_name", "unknown"))}) as retrieve_span:
        try:
            manifest, release_chunks = _load_or_build_release(
                chunks,
                provider=provider,
                database=db,
                allow_build=effective_allow_build,
            )
            release_id = manifest.release_id
            vector_candidates = _vector_candidates(
                query,
                database=db,
                release_id=release_id,
                provider=provider,
                limit=len(release_chunks) or len(chunks),
            )
        except _IndexStaleError:
            retrieve_span.set_attributes({"outcome": "failed", "fallback_reason": "index_stale", "duration_ms": max(0.0, (time.monotonic() - started) * 1000)})
            return RetrievalResult.unavailable(reason="index_stale")
        except Exception:
            retrieve_span.set_attributes({"outcome": "failed", "fallback_reason": "index_error", "duration_ms": max(0.0, (time.monotonic() - started) * 1000)})
            return RetrievalResult.unavailable(reason="index_error")

        lexical_candidates = _lexical_candidates(query, release_chunks, limit=len(release_chunks))
        if not lexical_candidates:
            retrieve_span.set_attributes({"outcome": "succeeded", "release_id": release_id, "fallback_reason": "no_matching_chunk", "candidate_count": len(vector_candidates), "hit_count": 0, "duration_ms": max(0.0, (time.monotonic() - started) * 1000)})
            return RetrievalResult.insufficient(release_id=release_id)

        fused = (
            fuse([vector_candidates, lexical_candidates])
            if _query_is_wordlike(query)
            else fuse([vector_candidates])
        )
        picked = select_with_diversity(fused, top_k=top_k, per_source_cap=per_source_cap)
        rerank_started = time.monotonic()
        with tel.sync_span("fitlife.rag.rerank", {"candidate_count": len(picked)}) as rerank_span:
            outcome = rerank(query, picked, reranker=reranker)
            rerank_span.set_attributes({
                "outcome": "succeeded",
                "hit_count": len(outcome.hits),
                **({"fallback_reason": outcome.reason} if outcome.reason else {}),
                "duration_ms": max(0.0, (time.monotonic() - rerank_started) * 1000),
            })

        hits = [
            Hit(
                chunk_id=item.chunk_id,
                content_hash=item.content_hash,
                source=item.source,
                heading=item.heading,
                text=item.text,
                rank=position,
                score=item.score,
            )
            for position, item in enumerate(outcome.hits, start=1)
        ]
        result = RetrievalResult.found(
            hits=hits,
            release_id=release_id or "release-unknown",
            retrieval_mode="hybrid",
            fallback_reason=outcome.reason,
        )
        retrieve_span.set_attributes({
            "outcome": "succeeded",
            "release_id": release_id or "release-unknown",
            "retrieval_mode": result.retrieval_mode or "hybrid",
            "candidate_count": len(fused),
            "hit_count": len(hits),
            **({"fallback_reason": outcome.reason} if outcome.reason else {}),
            "duration_ms": max(0.0, (time.monotonic() - started) * 1000),
        })
        return result


def _vector_candidates(
    query: str,
    *,
    database: PostgresDatabase,
    release_id: str,
    provider: EmbeddingProvider,
    limit: int,
) -> list[Hit]:
    query_vector = provider.embed_query(query)
    results = PgVectorReleaseStore(database).search_vectors(
        query_vector,
        top_k=limit,
        release_id=release_id,
    )
    candidates: list[Hit] = []
    for position, item in enumerate(results, start=1):
        candidates.append(
            Hit(
                chunk_id=item["chunk_id"],
                content_hash=item["content_hash"],
                source=item["source"],
                heading=item["heading"],
                text=item["text"],
                rank=position,
                score=item.get("score"),
            )
        )
    return candidates


def _lexical_candidates(query: str, chunks: list[dict], *, limit: int) -> list[Hit]:
    scored = []
    for chunk in chunks:
        searchable = f"{chunk['source']} {chunk['heading']} {chunk['text']}"
        score = score_text(query, searchable)
        if score <= 0:
            continue
        scored.append((score, chunk))
    scored.sort(key=lambda item: (-item[0], item[1]["chunk_id"]))
    return [
        Hit(
            chunk_id=chunk["chunk_id"],
            content_hash=chunk["content_hash"],
            source=chunk["source"],
            heading=chunk["heading"],
            text=chunk["text"],
            rank=position,
            score=score,
        )
        for position, (score, chunk) in enumerate(scored[:limit], start=1)
    ]


def _load_or_build_release(
    chunks: list[dict],
    *,
    provider: EmbeddingProvider,
    database: PostgresDatabase,
    allow_build: bool = True,
) -> tuple[IndexManifest, list[dict]]:
    """Return an active valid release and cached chunks from PostgreSQL."""
    documents = _documents_from_chunks(chunks)
    manifest = read_manifest(database)
    if manifest is not None and index_is_valid(
        manifest, provider=provider, documents=documents, chunk_count=len(chunks)
    ):
        cache_key = (database.dsn, database.target_schema, manifest.release_id)
        cached = _INDEX_CACHE.get(cache_key)
        if cached is not None and len(cached[1]) == len(chunks):
            return cached
        loaded = load_release(database)
        if loaded is not None:
            loaded_manifest, loaded_chunks = loaded
            if len(loaded_chunks) == len(chunks):
                entry = (loaded_manifest, loaded_chunks)
                _INDEX_CACHE[cache_key] = entry
                return entry

    if not allow_build:
        raise _IndexStaleError("index_stale")

    publish_release(
        chunks=chunks,
        provider=provider,
        embedding_lookup=provider.embed_query,
        documents=documents,
        database=database,
    )
    loaded = load_release(database)
    if loaded is None:
        raise RuntimeError("a published release could not be read back")
    loaded_manifest, loaded_chunks = loaded
    entry = (loaded_manifest, loaded_chunks)
    _INDEX_CACHE[(database.dsn, database.target_schema, loaded_manifest.release_id)] = entry
    return entry


def _documents_from_chunks(chunks: list[dict]) -> list[dict]:
    """Rebuild the corpus view a manifest digest needs from the chunks themselves."""
    documents: list[dict] = []
    current_source: str | None = None
    for chunk in chunks:
        if chunk["source"] != current_source:
            current_source = chunk["source"]
            documents.append({"source": current_source, "text": ""})
        documents[-1]["text"] += chunk["text"] + "\n"
    return documents


def active_release_id(*, database: PostgresDatabase | None = None) -> str | None:
    """The release currently active in PostgreSQL, when one exists."""
    manifest = read_manifest(_resolve_database(database))
    return manifest.release_id if manifest is not None else None


def _query_is_wordlike(query: str) -> bool:
    for token in tokenize(query):
        if len(token) >= 2 and token.isascii():
            return True
    return False
