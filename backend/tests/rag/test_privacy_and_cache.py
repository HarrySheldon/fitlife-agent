"""M0 regression tests: remote embedding privacy opt-in and request-path index caching."""
from __future__ import annotations

from pathlib import Path

from backend.config import Settings
from backend.rag import retriever
from backend.rag.build import main as build_cli_main
from backend.rag.vector_store import (
    HashingEmbeddingProvider,
    OpenAIEmbeddingProvider,
    build_embedding_provider,
)


def test_openai_api_key_alone_does_not_enable_remote_embedding(monkeypatch):
    """Setting OPENAI_API_KEY must not silently route legacy queries to remote embeddings."""
    settings = Settings(openai_api_key="sk-test-deployment-key")
    provider = build_embedding_provider(settings=settings)
    assert isinstance(provider, HashingEmbeddingProvider)
    assert provider.provider_name == "hashing"


def test_remote_embedding_requires_explicit_opt_in():
    class _FakeClient:
        pass

    settings = Settings(
        openai_api_key="sk-test-deployment-key",
        rag_embedding_provider="openai",
    )
    provider = build_embedding_provider(settings=settings, client=_FakeClient())
    assert isinstance(provider, OpenAIEmbeddingProvider)
    assert provider.provider_name == "openai"


def test_retrieve_detailed_returns_index_stale_without_writing_when_build_disabled(pg_db):
    retriever.clear_index_cache()
    result = retriever.retrieve_detailed(
        "protein",
        top_k=3,
        provider=HashingEmbeddingProvider(),
        database=pg_db,
        allow_build=False,
    )
    assert result.status == "unavailable"
    assert result.fallback_reason == "index_stale"
    assert retriever.active_release_id(database=pg_db) is None


def test_build_index_and_in_process_cache_avoids_disk_reload(pg_db, monkeypatch):
    retriever.clear_index_cache()
    release_id = retriever.build_knowledge_index(
        provider=HashingEmbeddingProvider(),
        database=pg_db,
    )
    assert release_id.startswith("release-")

    def _fail_load_release(_database=None):
        raise AssertionError("load_release should not be called on a warm cache hit")

    monkeypatch.setattr(retriever, "load_release", _fail_load_release)
    result = retriever.retrieve_detailed(
        "protein",
        top_k=2,
        provider=HashingEmbeddingProvider(),
        database=pg_db,
        allow_build=False,
    )
    assert result.status == "ok"
    assert result.release_id == release_id
    assert len(result.hits) >= 1


def test_rag_build_cli_publishes_release(make_isolated_pg_db, capsys):
    retriever.clear_index_cache()
    db = make_isolated_pg_db()
    exit_code = build_cli_main(["--database-url", db.dsn, "--schema", db.target_schema])
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert '"release_id":"release-0000"' in captured
    assert '"provider":"hashing"' in captured
    assert f'"schema":"{db.target_schema}"' in captured
