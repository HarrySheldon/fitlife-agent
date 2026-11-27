"""Cross-encoder neural reranker adapters and deterministic fallback scorer."""
from __future__ import annotations

from typing import Any, Protocol, Sequence

import httpx

from backend.rag.bm25 import tokenize_bm25


class Reranker(Protocol):
    def __call__(self, query: str, hits: Sequence[Any]) -> dict[str, float]:
        ...


class LexicalCrossReranker:
    """Deterministic local cross-scorer over query-passage token & phrase overlap."""

    def __call__(self, query: str, hits: Sequence[Any]) -> dict[str, float]:
        q_norm = query.strip().lower()
        q_terms = set(tokenize_bm25(query))
        scores: dict[str, float] = {}
        for hit in hits:
            body_text = f"{getattr(hit, 'heading', '')} {getattr(hit, 'text', '')}".lower()
            doc_terms = set(tokenize_bm25(body_text))
            overlap = len(q_terms & doc_terms) / max(1, len(q_terms))
            heading_terms = set(tokenize_bm25(str(getattr(hit, "heading", ""))))
            heading_overlap = len(q_terms & heading_terms) / max(1, len(q_terms))
            exact_phrase_bonus = 0.35 if (len(q_norm) >= 2 and q_norm in body_text) else 0.0
            base_score = float(getattr(hit, "score", 0.0) or 0.0)
            scores[hit.chunk_id] = overlap + 0.5 * heading_overlap + exact_phrase_bonus + 0.1 * base_score
        return scores


class BgeReranker:
    """HTTP adapter for BGE-Reranker endpoints (SiliconFlow / TEI / Jina / Cohere shapes)."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        model: str = "BAAI/bge-reranker-v2-m3",
        timeout_seconds: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._client = client

    def __call__(self, query: str, hits: Sequence[Any]) -> dict[str, float]:
        if not hits:
            return {}
        documents = [f"{hit.heading}\n{hit.text}" for hit in hits]
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        endpoint = self.base_url if self.base_url.endswith("/rerank") else f"{self.base_url}/rerank"
        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
            "return_documents": False,
        }
        if self._client is not None:
            response = self._client.post(endpoint, json=payload, headers=headers, timeout=self.timeout_seconds)
        else:
            with httpx.Client(timeout=self.timeout_seconds, trust_env=False) as http:
                response = http.post(endpoint, json=payload, headers=headers)
        response.raise_for_status()
        body = response.json()
        items = body.get("results") if isinstance(body, dict) else body
        if not isinstance(items, list):
            raise ValueError("Invalid rerank payload")

        scores: dict[str, float] = {}
        for item in items:
            idx = item.get("index")
            raw_score = item.get("relevance_score", item.get("score"))
            if not isinstance(idx, int) or not 0 <= idx < len(hits):
                raise ValueError("Invalid rerank index")
            scores[hits[idx].chunk_id] = float(raw_score)
        return scores


def build_reranker(settings: Any = None):
    if settings is None:
        from backend.config import get_settings

        settings = get_settings()
    provider = getattr(settings, "rag_reranker_provider", "none") or "none"
    if provider == "lexical":
        return LexicalCrossReranker()
    if provider == "bge" and getattr(settings, "rag_reranker_base_url", None):
        return BgeReranker(
            base_url=settings.rag_reranker_base_url,
            api_key=getattr(settings, "rag_reranker_api_key", None),
            model=getattr(settings, "rag_reranker_model", "BAAI/bge-reranker-v2-m3"),
        )
    return None
