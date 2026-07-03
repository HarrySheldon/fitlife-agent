from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backend.rag.vector_store import (
    HashingEmbeddingProvider,
    OpenAIEmbeddingProvider,
    VectorIndex,
    cosine_similarity,
)


def test_hashing_embedding_provider_is_deterministic_and_normalized():
    provider = HashingEmbeddingProvider(dimensions=16)

    first = provider.embed_query("protein target and calories")
    second = provider.embed_query("protein target and calories")

    assert first == second
    assert len(first) == 16
    assert abs(sum(value * value for value in first) - 1.0) < 0.0001


def test_cosine_similarity_prefers_matching_vectors():
    query = [1.0, 0.0, 0.0]

    assert cosine_similarity(query, [1.0, 0.0, 0.0]) > cosine_similarity(query, [0.0, 1.0, 0.0])


def test_vector_index_ranks_matching_chunks_first():
    provider = HashingEmbeddingProvider(dimensions=32)
    chunks = [
        {"source": "fitness_rules.md", "heading": "Training", "text": "strength workout rest day"},
        {"source": "nutrition_guidelines.md", "heading": "Protein", "text": "protein calories meal target"},
    ]
    index = VectorIndex.build(chunks, provider=provider)

    results = index.search("protein meal", provider=provider, top_k=2)

    assert results[0]["source"] == "nutrition_guidelines.md"
    assert results[0]["score"] >= results[1]["score"]


def test_vector_index_round_trips_json():
    provider = HashingEmbeddingProvider(dimensions=8)
    chunks = [{"source": "meal_templates.md", "heading": "Snacks", "text": "yogurt nuts fruit"}]
    index = VectorIndex.build(chunks, provider=provider)
    path = Path("backend/data/test_vector_index_runtime.json")

    index.save(path)
    restored = VectorIndex.load(path)

    assert restored.entries == index.entries
    assert restored.embedding_model == index.embedding_model
    assert restored.embedding_dimensions == index.embedding_dimensions


def test_openai_embedding_provider_calls_embeddings_api():
    class FakeEmbeddings:
        def __init__(self):
            self.calls: list[dict] = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.2, 0.8])])

    class FakeClient:
        def __init__(self):
            self.embeddings = FakeEmbeddings()

    client = FakeClient()
    provider = OpenAIEmbeddingProvider(client=client, model="text-embedding-test")

    embedding = provider.embed_query("protein")

    assert embedding == [0.2, 0.8]
    assert client.embeddings.calls == [{"model": "text-embedding-test", "input": "protein"}]
