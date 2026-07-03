from __future__ import annotations

from backend.rag import retriever
from backend.rag.retriever import retrieve_knowledge


class FakeKeywordEmbeddingProvider:
    model_name = "fake-keyword-embedding"
    dimensions = 2

    def embed_query(self, text: str) -> list[float]:
        if "protein" in text.lower():
            return [1.0, 0.0]
        return [0.0, 1.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


def test_retriever_uses_vector_index_and_preserves_source_diversity(monkeypatch):
    chunks = [
        {"source": "nutrition_guidelines.md", "heading": "Protein", "text": "protein target one"},
        {"source": "nutrition_guidelines.md", "heading": "Protein", "text": "protein target two"},
        {"source": "meal_templates.md", "heading": "Meals", "text": "protein tofu meal"},
    ]
    monkeypatch.setattr(retriever, "load_knowledge_chunks", lambda: chunks)

    results = retrieve_knowledge("protein", top_k=2, provider=FakeKeywordEmbeddingProvider())

    assert [item["source"] for item in results] == ["nutrition_guidelines.md", "meal_templates.md"]
    assert all("score" in item for item in results)
