from __future__ import annotations

from pathlib import Path

from backend.config import get_settings
from backend.rag.contracts import Hit, RetrievalResult
from backend.rag.index_release import index_is_valid, load_release, publish_release, read_manifest
from backend.rag.ingest import ensure_chunk_identity, load_knowledge_chunks
from backend.rag.ranking import fuse, rerank, select_with_diversity
from backend.rag.vector_store import EmbeddingProvider, VectorIndex, build_embedding_provider, score_text


def retrieve_knowledge(
    query: str,
    top_k: int = 3,
    *,
    provider: EmbeddingProvider | None = None,
    index_path: str | Path | None = None,
) -> list[dict]:
    """Compatibility entry: just the hits, still the same plain list of dicts.

    It deliberately returns an empty list when there is no evidence. The previous
    behaviour - returning the first ``top_k`` chunks when nothing scored - made an
    unanswerable question look supported.
    """
    result = retrieve_detailed(query, top_k, provider=provider, index_path=index_path)
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
    index_path: str | Path | None = None,
    reranker=None,
    per_source_cap: int = 2,
) -> RetrievalResult:
    """The full answer: status, hits, release, mode and why it fell back."""
    chunks = ensure_chunk_identity(load_knowledge_chunks())
    provider = provider or build_embedding_provider()
    index_path = Path(index_path) if index_path is not None else get_settings().vector_index_path

    try:
        index = _load_or_build_index(chunks, provider=provider, index_path=index_path)
        release_id = active_release_id(index_path)
        vector_candidates = _vector_candidates(query, index, provider=provider,
                                               limit=len(chunks))
    except Exception:
        # A broken index is not "no results"; it is a different answer.
        return RetrievalResult.unavailable(reason="index_error")

    lexical_candidates = _lexical_candidates(query, chunks, limit=len(chunks))
    if not lexical_candidates:
        # Calibrated on the development set and deliberately conservative: with hashing
        # embeddings the vector score is not a semantic confidence signal, so without at
        # least one term match this implementation does not claim support. This is a
        # local rule, not a validated semantic threshold.
        return RetrievalResult.insufficient(release_id=release_id)

    # The lexical list is intentionally withheld from fusion, only used as the evidence
    # gate above. Measured reason: the tokenizer splits Chinese into single characters,
    # so a long Chinese paragraph "matches" almost any Chinese query (coverage 0.55-0.75)
    # while the genuinely relevant English chunks score 0.00. Feeding that list into
    # fusion ranked the long paragraph above the real evidence and cost the
    # multi-evidence case. Fusion stays in place for the day a second comparable
    # retriever exists; a single list fuses to its own rank order.
    fused = fuse([vector_candidates])
    picked = select_with_diversity(fused, top_k=top_k, per_source_cap=per_source_cap)
    outcome = rerank(query, picked, reranker=reranker)

    hits = [
        Hit(chunk_id=item.chunk_id, content_hash=item.content_hash, source=item.source,
            heading=item.heading, text=item.text, rank=position, score=item.score)
        for position, item in enumerate(outcome.hits, start=1)
    ]
    return RetrievalResult.found(
        hits=hits,
        release_id=release_id or "release-unknown",
        retrieval_mode="hybrid",
        fallback_reason=outcome.reason,
    )


def _vector_candidates(query: str, index: VectorIndex, *, provider: EmbeddingProvider,
                       limit: int) -> list[Hit]:
    results = index.search(query, provider=provider, top_k=limit)
    candidates: list[Hit] = []
    for position, item in enumerate(results, start=1):
        candidates.append(Hit(
            chunk_id=item["chunk_id"],
            content_hash=item["content_hash"],
            source=item["source"],
            heading=item["heading"],
            text=item["text"],
            rank=position,
            score=item.get("score"),
        ))
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
        Hit(chunk_id=chunk["chunk_id"], content_hash=chunk["content_hash"],
            source=chunk["source"], heading=chunk["heading"], text=chunk["text"],
            rank=position, score=score)
        for position, (score, chunk) in enumerate(scored[:limit], start=1)
    ]


def _release_root(index_path: Path) -> Path:
    """Releases live beside the legacy index file, one directory per release."""
    return index_path.parent / f"{index_path.stem}-releases"


def _load_or_build_index(
    chunks: list[dict],
    *,
    provider: EmbeddingProvider,
    index_path: Path,
) -> VectorIndex:
    """Return an index that provably matches these chunks.

    Validity is decided by the release manifest, not by comparing a model name and a
    chunk count. That comparison was the R0 defect: editing a document without changing
    how many chunks it produced kept serving the old text back.
    """
    root = _release_root(index_path)
    documents = _documents_from_chunks(chunks)
    loaded = load_release(root)
    if loaded is not None:
        manifest, payload = loaded
        if index_is_valid(manifest, provider=provider, documents=documents,
                          chunk_count=len(chunks)):
            entries = payload.get("entries", [])
            if len(entries) == len(chunks):
                return VectorIndex(
                    entries=[{"chunk": {k: v for k, v in entry.items() if k != "embedding"},
                              "embedding": entry["embedding"]} for entry in entries],
                    embedding_model=manifest.embedding_model,
                    embedding_dimensions=manifest.embedding_dimensions,
                )
        previous_root = root / manifest.release_id if (root / manifest.release_id).exists() else None
    else:
        previous_root = None

    publish_release(
        chunks=chunks,
        provider=provider,
        embedding_lookup=provider.embed_query,
        root=root,
        release_id=_next_release_id(root),
        documents=documents,
        previous_root=previous_root,
    )
    loaded = load_release(root)
    if loaded is None:  # pragma: no cover - publish_release either raises or activates
        raise RuntimeError("a published release could not be read back")
    manifest, payload = loaded
    return VectorIndex(
        entries=[{"chunk": {k: v for k, v in entry.items() if k != "embedding"},
                  "embedding": entry["embedding"]} for entry in payload.get("entries", [])],
        embedding_model=manifest.embedding_model,
        embedding_dimensions=manifest.embedding_dimensions,
    )


def _next_release_id(root: Path) -> str:
    """Monotonic, collision-free release ids without reading a clock."""
    existing = 0
    if root.exists():
        for child in root.iterdir():
            if child.is_dir() and child.name.startswith("release-"):
                try:
                    existing = max(existing, int(child.name.split("-", 1)[1]) + 1)
                except (IndexError, ValueError):
                    continue
    return f"release-{existing:04d}"


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


def active_release_id(index_path: str | Path) -> str | None:
    """The release currently active for this index location, when one exists."""
    manifest = read_manifest(_release_root(Path(index_path)))
    return manifest.release_id if manifest is not None else None

