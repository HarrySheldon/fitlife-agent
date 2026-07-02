from __future__ import annotations

from backend.rag.ingest import load_knowledge_chunks
from backend.rag.vector_store import score_text


def retrieve_knowledge(query: str, top_k: int = 3) -> list[dict]:
    chunks = load_knowledge_chunks()
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
