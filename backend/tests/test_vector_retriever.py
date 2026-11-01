from __future__ import annotations

from backend.rag import retriever
from backend.rag.retriever import retrieve_detailed, retrieve_knowledge


class FakeKeywordEmbeddingProvider:
    provider_name = "fake"
    model_name = "fake-keyword-embedding"
    dimensions = 2

    def embed_query(self, text: str) -> list[float]:
        if "protein" in text.lower():
            return [1.0, 0.0]
        return [0.0, 1.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


def _chunks():
    return [
        {"source": "nutrition_guidelines.md", "heading": "Protein", "text": "protein target one"},
        {"source": "nutrition_guidelines.md", "heading": "Protein", "text": "protein target two"},
        {"source": "meal_templates.md", "heading": "Meals", "text": "protein tofu meal"},
    ]


def test_the_retriever_uses_the_vector_index_and_respects_top_k(monkeypatch):
    """R3 changed one rule here on purpose; the earlier assertion is kept below.

    The previous contract was "at most one chunk per source". That rule is what made a
    multi-evidence question lose half its support, so the per-source limit became a cap
    (default 2) rather than a hard one. Diversity is still available on request - see
    the next test - but it is no longer imposed where it hides relevant text.
    """
    monkeypatch.setattr(retriever, "load_knowledge_chunks", _chunks)

    results = retrieve_knowledge("protein", top_k=2, provider=FakeKeywordEmbeddingProvider())

    assert len(results) == 2
    assert all("score" in item for item in results)
    assert all(item["chunk_id"].startswith("chunk-") for item in results)


def test_a_stricter_per_source_cap_still_diversifies(monkeypatch):
    """The old behaviour remains reachable: cap 1 gives one chunk per source."""
    monkeypatch.setattr(retriever, "load_knowledge_chunks", _chunks)

    result = retrieve_detailed("protein", top_k=2, provider=FakeKeywordEmbeddingProvider(),
                               per_source_cap=1)

    assert [hit.source for hit in result.hits] == [
        "nutrition_guidelines.md", "meal_templates.md"]


def test_two_chunks_from_one_source_can_both_surface(monkeypatch):
    """The R3 fix: a document holding the two best chunks is allowed both."""
    monkeypatch.setattr(retriever, "load_knowledge_chunks", _chunks)

    result = retrieve_detailed("protein", top_k=3, provider=FakeKeywordEmbeddingProvider())

    sources = [hit.source for hit in result.hits]
    assert sources.count("nutrition_guidelines.md") == 2


def test_an_off_topic_query_returns_no_hits(monkeypatch):
    """No term match means no claim of support, not a pile of near misses."""
    monkeypatch.setattr(retriever, "load_knowledge_chunks", _chunks)

    result = retrieve_detailed("quantum chromodynamics", top_k=3,
                               provider=FakeKeywordEmbeddingProvider())

    assert result.status == "insufficient"
    assert result.hits == []


def test_a_supported_query_reports_a_release_and_a_mode(monkeypatch):
    monkeypatch.setattr(retriever, "load_knowledge_chunks", _chunks)

    result = retrieve_detailed("protein", top_k=2, provider=FakeKeywordEmbeddingProvider())

    assert result.status == "ok"
    assert result.release_id
    assert result.retrieval_mode == "hybrid"


def test_hits_are_ranked_contiguously_from_one(monkeypatch):
    monkeypatch.setattr(retriever, "load_knowledge_chunks", _chunks)

    result = retrieve_detailed("protein", top_k=3, provider=FakeKeywordEmbeddingProvider())

    assert [hit.rank for hit in result.hits] == list(range(1, len(result.hits) + 1))
