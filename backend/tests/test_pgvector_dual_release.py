"""Phase 3 tests for pgvector dual-version RAG releases, HNSW cosine search, rollback, and GC."""
from __future__ import annotations

import math

import pytest

from backend.rag.contracts import chunk_id, content_hash, document_version
from backend.rag.pgvector_store import PgVectorReleaseStore
from backend.rag.retriever import (
    active_release_id,
    build_knowledge_index,
    clear_index_cache,
    retrieve_detailed,
)
from backend.rag.vector_store import HashingEmbeddingProvider


def _make_doc_and_chunk(source: str, heading: str, body: str, ordinal: int = 0):
    doc = {"source": source, "text": f"# {heading}\n{body}"}
    chunk = {
        "chunk_id": chunk_id(source, heading, ordinal),
        "content_hash": content_hash(body),
        "document_version": document_version(doc["text"]),
        "source": source,
        "heading": heading,
        "text": body,
        "ordinal": ordinal,
    }
    return doc, chunk


def test_pgvector_dual_release_incremental_hnsw_rollback_and_gc(pg_db):
    store = PgVectorReleaseStore(pg_db)
    provider = HashingEmbeddingProvider(dimensions=64)

    doc_a1, chunk_a1 = _make_doc_and_chunk("nutrition.md", "Protein", "Consume 1.6g protein per kg bodyweight")
    doc_b1, chunk_b1 = _make_doc_and_chunk("sleep.md", "Recovery", "Aim for 8 hours quality sleep nightly")

    embedded: list[str] = []

    def lookup(text: str) -> list[float]:
        embedded.append(text)
        return provider.embed_query(text)

    r1 = store.publish_release(
        chunks=[chunk_a1, chunk_b1],
        provider=provider,
        embedding_lookup=lookup,
        documents=[doc_a1, doc_b1],
    )
    assert r1 == "release-0000"
    assert len(embedded) == 2

    with pg_db.connection() as conn:
        hnsw = conn.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = current_schema()
              AND tablename = 'rag_chunks'
              AND indexname = 'idx_rag_chunks_hnsw_d64'
            """
        ).fetchone()
    assert hnsw is not None
    assert "hnsw" in hnsw["indexdef"].lower()

    # Release 2: change nutrition doc only -> sleep chunk vector is reused without calling lookup
    doc_a2, chunk_a2 = _make_doc_and_chunk("nutrition.md", "Protein", "Consume 2.0g protein per kg bodyweight")
    embedded.clear()
    r2 = store.publish_release(
        chunks=[chunk_a2, chunk_b1],
        provider=provider,
        embedding_lookup=lookup,
        documents=[doc_a2, doc_b1],
    )
    assert r2 == "release-0001"
    assert len(embedded) == 1
    assert embedded[0] == chunk_a2["text"]

    # Failed build must keep release-0001 active
    doc_fail, chunk_fail = _make_doc_and_chunk("fail.md", "Fail", "Unpublished body")
    with pytest.raises(ValueError, match="finite"):
        store.publish_release(
            chunks=[chunk_fail],
            provider=provider,
            embedding_lookup=lambda _t: [float("nan")] * 64,
            documents=[doc_fail],
        )
    assert store.read_manifest().release_id == "release-0001"

    # Native cosine search hits protein chunk first with finite score
    hits = store.search_vectors(provider.embed_query("protein kg"), top_k=2)
    assert len(hits) == 2
    assert hits[0]["source"] == "nutrition.md"
    assert math.isfinite(hits[0]["score"])

    # Release 3 triggers GC with keep_previous=1 -> release-0000 removed, 0001 and 0002 kept
    doc_c, chunk_c = _make_doc_and_chunk("water.md", "Hydration", "Drink water throughout training")
    r3 = store.publish_release(
        chunks=[chunk_c],
        provider=provider,
        embedding_lookup=lookup,
        documents=[doc_c],
        keep_previous=1,
    )
    assert r3 == "release-0002"
    ids = [rel["release_id"] for rel in store.list_releases()]
    assert ids == ["release-0001", "release-0002"]

    # Atomic rollback switches active release back to release-0001
    restored = store.rollback_release()
    assert restored == "release-0001"
    manifest = store.read_manifest()
    assert manifest is not None and manifest.release_id == "release-0001"
    ptr = store.pointer_state()
    assert ptr == {"active_release_id": "release-0001", "previous_release_id": "release-0002"}


def test_retriever_and_cache_use_pgvector_store(pg_db):
    clear_index_cache()
    provider = HashingEmbeddingProvider()
    release_id = build_knowledge_index(provider=provider, database=pg_db)
    assert release_id == active_release_id(database=pg_db)

    result = retrieve_detailed(
        "protein intake recommendation",
        top_k=3,
        provider=provider,
        database=pg_db,
        allow_build=False,
    )
    assert result.status == "ok"
    assert result.release_id == release_id
    assert len(result.hits) >= 1
