from __future__ import annotations

from pathlib import Path

from backend.config import get_settings
from backend.rag.ingest import load_knowledge_chunks
from backend.rag.vector_store import EmbeddingProvider, VectorIndex, build_embedding_provider, score_text


def retrieve_knowledge(
    query: str,
    top_k: int = 3,
    *,
    provider: EmbeddingProvider | None = None,
    index_path: str | Path | None = None,
) -> list[dict]:
    chunks = load_knowledge_chunks()
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


def _load_or_build_index(
    chunks: list[dict],
    *,
    provider: EmbeddingProvider,
    index_path: Path,
) -> VectorIndex:
    if index_path.exists():
        try:
            index = VectorIndex.load(index_path)
            if index.embedding_model == provider.model_name and len(index.entries) == len(chunks):
                return index
        except Exception:
            pass

    index = VectorIndex.build(chunks, provider=provider)
    try:
        index.save(index_path)
    except Exception:
        pass
    return index


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
