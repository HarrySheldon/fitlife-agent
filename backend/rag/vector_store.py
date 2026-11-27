from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Protocol

import httpx

from backend.config import Settings, get_settings
from backend.rag.contextual import effective_search_text


TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def score_text(query: str, text: str) -> float:
    query_terms = Counter(tokenize(query))
    text_terms = Counter(tokenize(text))
    if not query_terms or not text_terms:
        return 0
    return float(sum(text_terms.get(term, 0) * weight for term, weight in query_terms.items()))


class EmbeddingProvider(Protocol):
    # Provider and model identity are separate facts: two providers can expose the same
    # model name, and a different provider invalidates an index even then.
    provider_name: str
    model_name: str
    dimensions: int

    def embed_query(self, text: str) -> list[float]:
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...


class HashingEmbeddingProvider:
    provider_name = "hashing"
    model_name = "local-hashing-embedding"

    def __init__(self, dimensions: int = 128):
        self.dimensions = dimensions

    def embed_query(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return _normalize(vector)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


class OpenAIEmbeddingProvider:
    provider_name = "openai"

    def __init__(self, *, client, model: str):
        self.client = client
        self.model_name = model
        self.dimensions = 0

    def embed_query(self, text: str) -> list[float]:
        response = self.client.embeddings.create(model=self.model_name, input=text)
        embedding = list(response.data[0].embedding)
        self.dimensions = len(embedding)
        return embedding

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(model=self.model_name, input=texts)
        embeddings = [list(item.embedding) for item in response.data]
        if embeddings:
            self.dimensions = len(embeddings[0])
        return embeddings


class BgeM3EmbeddingProvider:
    """OpenAI-compatible / TEI / SiliconFlow embedding client for BAAI/bge-m3."""

    provider_name = "bge-m3"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        model: str = "BAAI/bge-m3",
        dimensions: int = 1024,
        timeout_seconds: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds
        self._client = client

    def _post_embeddings(self, inputs: str | list[str]) -> list[list[float]]:
        endpoint = self.base_url if self.base_url.endswith("/embeddings") else f"{self.base_url}/embeddings"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {"model": self.model_name, "input": inputs, "encoding_format": "float"}
        if self._client is not None:
            response = self._client.post(endpoint, json=payload, headers=headers, timeout=self.timeout_seconds)
        else:
            with httpx.Client(timeout=self.timeout_seconds, trust_env=False) as http:
                response = http.post(endpoint, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json().get("data") or []
        if isinstance(data, list) and data and "index" in data[0]:
            data = sorted(data, key=lambda item: int(item["index"]))
        vectors = [_normalize([float(v) for v in item["embedding"]]) for item in data]
        if vectors and len(vectors[0]) > 0:
            self.dimensions = len(vectors[0])
        return vectors

    def embed_query(self, text: str) -> list[float]:
        vectors = self._post_embeddings(text)
        if not vectors:
            raise ValueError("Embedding response did not include a vector")
        return vectors[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._post_embeddings(texts)


def build_embedding_provider(*, settings: Settings | None = None, client=None) -> EmbeddingProvider:
    settings = settings or get_settings()
    if settings.rag_embedding_provider == "bge-m3" and (client is not None or settings.rag_embedding_base_url or settings.openai_base_url):
        base_url = settings.rag_embedding_base_url or settings.openai_base_url
        if base_url:
            return BgeM3EmbeddingProvider(
                base_url=base_url,
                api_key=settings.rag_embedding_api_key or settings.openai_api_key,
                model=settings.rag_embedding_model,
                client=client,
            )
    if settings.rag_embedding_provider == "openai" and (client is not None or settings.openai_api_key):
        if client is None:
            try:
                from openai import OpenAI
            except ImportError:
                return HashingEmbeddingProvider()

            kwargs: dict[str, str] = {"api_key": settings.openai_api_key}
            if settings.openai_base_url:
                kwargs["base_url"] = settings.openai_base_url
            client = OpenAI(**kwargs)
        return OpenAIEmbeddingProvider(client=client, model=settings.embedding_model)
    return HashingEmbeddingProvider()


class VectorIndex:
    def __init__(self, *, entries: list[dict], embedding_model: str, embedding_dimensions: int):
        self.entries = entries
        self.embedding_model = embedding_model
        self.embedding_dimensions = embedding_dimensions

    @classmethod
    def build(cls, chunks: list[dict], *, provider: EmbeddingProvider) -> "VectorIndex":
        texts = [_chunk_search_text(chunk) for chunk in chunks]
        embeddings = provider.embed_documents(texts)
        entries = []
        for chunk, embedding in zip(chunks, embeddings, strict=False):
            entries.append({"chunk": chunk, "embedding": embedding})
        dimensions = len(embeddings[0]) if embeddings else provider.dimensions
        return cls(entries=entries, embedding_model=provider.model_name, embedding_dimensions=dimensions)

    @classmethod
    def load(cls, path: str | Path) -> "VectorIndex":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            entries=payload["entries"],
            embedding_model=payload["embedding_model"],
            embedding_dimensions=payload["embedding_dimensions"],
        )

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "embedding_model": self.embedding_model,
            "embedding_dimensions": self.embedding_dimensions,
            "entries": self.entries,
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def search(self, query: str, *, provider: EmbeddingProvider, top_k: int = 3) -> list[dict]:
        query_embedding = provider.embed_query(query)
        scored = []
        for entry in self.entries:
            score = cosine_similarity(query_embedding, entry["embedding"])
            scored.append((score, entry["chunk"]))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [{**chunk, "score": score} for score, chunk in scored[:top_k]]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=False)) / (left_norm * right_norm)


def _chunk_search_text(chunk: dict) -> str:
    return f"{chunk.get('source', '')} {chunk.get('heading', '')} {effective_search_text(chunk)}"


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]
