from __future__ import annotations

from pathlib import Path

from backend.config import get_settings
from backend.rag.index_release import index_is_valid, load_release, publish_release
from backend.rag.ingest import ensure_chunk_identity, load_knowledge_chunks
from backend.rag.vector_store import EmbeddingProvider, VectorIndex, build_embedding_provider, score_text


def retrieve_knowledge(
    query: str,
    top_k: int = 3,
    *,
    provider: EmbeddingProvider | None = None,
    index_path: str | Path | None = None,
) -> list[dict]:
    chunks = ensure_chunk_identity(load_knowledge_chunks())
    provider = provider or build_embedding_provider()
    index_path = Path(index_path) if index_path is not None else get_settings().vector_index_path

    try:
        index = _load_or_build_index(chunks, provider=provider, index_path=index_path)
        vector_results = index.search(query, provider=provider, top_k=len(chunks))
        results = _source_diverse(_with_hybrid_scores(query, vector_results), top_k=top_k)
        if results:
            return results
    except Exception:
        pass

    return _lexical_retrieve(query, chunks, top_k=top_k)


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


def _with_hybrid_scores(query: str, vector_results: list[dict]) -> list[dict]:
    ranked = []
    for item in vector_results:
        searchable = f"{item['source']} {item['heading']} {item['text']}"
        lexical_score = score_text(query, searchable)
        ranked.append({**item, "score": item.get("score", 0.0) + lexical_score})
    return sorted(ranked, key=lambda item: item["score"], reverse=True)


def _source_diverse(results: list[dict], *, top_k: int) -> list[dict]:
    output: list[dict] = []
    seen_sources: set[str] = set()
    for item in results:
        if item.get("score", 0.0) <= 0:
            continue
        if item["source"] in seen_sources:
            continue
        output.append(item)
        seen_sources.add(item["source"])
        if len(output) >= top_k:
            break
    return output


def _lexical_retrieve(query: str, chunks: list[dict], *, top_k: int) -> list[dict]:
    scored = []
    for chunk in chunks:
        searchable = f"{chunk['source']} {chunk['heading']} {chunk['text']}"
        score = score_text(query, searchable)
        scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    results: list[dict] = []
    seen_sources: set[str] = set()
    for score, chunk in scored:
        if score <= 0:
            continue
        if chunk["source"] in seen_sources:
            continue
        results.append(chunk)
        seen_sources.add(chunk["source"])
        if len(results) >= top_k:
            break
    if results:
        return results
    return [chunk for _, chunk in scored[:top_k]]
