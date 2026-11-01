"""R2: an index is valid for exactly one corpus, and a release replaces it atomically.

R0 reproduced the failure this prevents: the loader compared only the embedding model
name and the chunk count, so editing a document without changing how many chunks it
produced kept serving the old text. Searching a term that only exists in the new version
returned the old version's chunks.

The rule this stage installs is that validity is decided by a manifest, not by a guess
derived from shape. A manifest names the corpus digest, the chunking version, the
embedding configuration and the dimensions; if any of them differ, the index is stale.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.rag.contracts import (
    CHUNKING_VERSION,
    IndexManifest,
    content_hash,
    corpus_digest,
    document_version,
)


def _documents(alpha: str = "alpha", beta: str = "beta") -> list[dict]:
    return [
        {"source": "a.md", "text": f"# Notes\n{alpha}"},
        {"source": "b.md", "text": f"# Notes\n{beta}"},
    ]


def _manifest(provider, *, documents, chunk_count, **overrides) -> IndexManifest:
    values = {
        "schema_version": 1,
        "release_id": "release-0001",
        "corpus_digest": corpus_digest(documents),
        "chunking_version": CHUNKING_VERSION,
        "embedding_provider": provider.provider_name,
        "embedding_model": provider.model_name,
        "embedding_dimensions": provider.dimensions,
        "config_digest": content_hash(f"{provider.provider_name}:{provider.model_name}"),
        "chunk_count": chunk_count,
    }
    values.update(overrides)
    return IndexManifest(**values)


def _provider():
    from backend.rag.vector_store import HashingEmbeddingProvider

    return HashingEmbeddingProvider()


# --------------------------------------------------------------------------
# validity is decided by the manifest
# --------------------------------------------------------------------------

def test_a_matching_manifest_marks_the_index_valid():
    from backend.rag.index_release import index_is_valid

    provider = _provider()
    documents = _documents()
    manifest = _manifest(provider, documents=documents, chunk_count=2)

    assert index_is_valid(manifest, provider=provider, documents=documents,
                          chunk_count=2)


def test_a_same_length_content_edit_invalidates_the_index():
    """GAP 2 fix: two documents with identical shape but different text."""
    from backend.rag.index_release import index_is_valid

    provider = _provider()
    before = _documents("alpha", "beta")
    after = _documents("alphi", "beto")  # same lengths, same chunk count
    manifest = _manifest(provider, documents=before, chunk_count=2)

    assert manifest.chunk_count == 2
    assert not index_is_valid(manifest, provider=provider, documents=after,
                              chunk_count=2)


def test_a_different_chunking_version_invalidates_the_index():
    from backend.rag.index_release import index_is_valid

    provider = _provider()
    documents = _documents()
    manifest = _manifest(provider, documents=documents, chunk_count=2,
                         chunking_version="markdown-heading-v1")

    assert not index_is_valid(manifest, provider=provider, documents=documents,
                              chunk_count=2)


def test_a_different_model_invalidates_the_index():
    from backend.rag.index_release import index_is_valid

    provider = _provider()
    documents = _documents()
    manifest = _manifest(provider, documents=documents, chunk_count=2,
                         embedding_model="some-other-model")

    assert not index_is_valid(manifest, provider=provider, documents=documents,
                              chunk_count=2)


def test_a_different_dimension_invalidates_the_index():
    from backend.rag.index_release import index_is_valid

    provider = _provider()
    documents = _documents()
    manifest = _manifest(provider, documents=documents, chunk_count=2,
                         embedding_dimensions=provider.dimensions + 1)

    assert not index_is_valid(manifest, provider=provider, documents=documents,
                              chunk_count=2)


def test_a_different_provider_invalidates_the_index():
    from backend.rag.index_release import index_is_valid

    provider = _provider()
    documents = _documents()
    manifest = _manifest(provider, documents=documents, chunk_count=2,
                         embedding_provider="some-other-provider")

    assert not index_is_valid(manifest, provider=provider, documents=documents,
                              chunk_count=2)


def test_a_different_chunk_count_invalidates_the_index():
    from backend.rag.index_release import index_is_valid

    provider = _provider()
    documents = _documents()
    manifest = _manifest(provider, documents=documents, chunk_count=2)

    assert not index_is_valid(manifest, provider=provider, documents=documents,
                              chunk_count=3)


# --------------------------------------------------------------------------
# an index that cannot be trusted must not be published
# --------------------------------------------------------------------------- 

def _chunks():
    from backend.rag.ingest import chunk_markdown

    return [chunk for document in _documents() for chunk in chunk_markdown(document)]


def test_an_index_with_missing_vectors_is_refused(tmp_path):
    from backend.rag.index_release import publish_release

    provider = _provider()
    chunks = _chunks()
    with pytest.raises(ValueError, match="vector"):
        publish_release(chunks=chunks, provider=provider,
                        embedding_lookup=lambda _text: [], root=tmp_path,
                        release_id="release-0001", documents=_documents())


def test_an_index_with_a_non_finite_vector_is_refused(tmp_path):
    from backend.rag.index_release import publish_release

    provider = _provider()
    chunks = _chunks()
    calls = {"n": 0}

    def lookup(_text):
        calls["n"] += 1
        if calls["n"] == 1:
            return [float("nan")] * provider.dimensions
        return [0.1] * provider.dimensions

    with pytest.raises(ValueError, match="finite"):
        publish_release(chunks=chunks, provider=provider,
                        embedding_lookup=lookup, root=tmp_path,
                        release_id="release-0001", documents=_documents())


def test_an_index_with_a_ragged_dimension_is_refused(tmp_path):
    from backend.rag.index_release import publish_release

    provider = _provider()
    chunks = _chunks()
    calls = {"n": 0}

    def lookup(_text):
        calls["n"] += 1
        width = provider.dimensions if calls["n"] == 1 else provider.dimensions - 1
        return [0.1] * width

    with pytest.raises(ValueError, match="dimension"):
        publish_release(chunks=chunks, provider=provider,
                        embedding_lookup=lookup, root=tmp_path,
                        release_id="release-0001", documents=_documents())


def test_duplicate_chunk_ids_are_refused(tmp_path):
    """Two chunks claiming one id would make a citation ambiguous."""
    from backend.rag.index_release import publish_release

    provider = _provider()
    chunks = _chunks()
    chunks[1] = {**chunks[1], "chunk_id": chunks[0]["chunk_id"]}
    lookup = lambda _text: [0.1] * provider.dimensions  # noqa: E731

    with pytest.raises(ValueError, match="unique"):
        publish_release(chunks=chunks, provider=provider,
                        embedding_lookup=lookup, root=tmp_path,
                        release_id="release-0001", documents=_documents())


# --------------------------------------------------------------------------
# publishing is atomic and an interrupted build keeps the previous release
# --------------------------------------------------------------------------

def test_publishing_creates_a_release_with_a_readable_manifest(tmp_path):
    from backend.rag.index_release import publish_release, read_manifest

    provider = _provider()
    chunks = _chunks()
    lookup = lambda _text: [0.1] * provider.dimensions  # noqa: E731

    release = publish_release(chunks=chunks, provider=provider,
                              embedding_lookup=lookup, root=tmp_path,
                              release_id="release-0001",
                              documents=_documents())

    manifest = read_manifest(tmp_path)
    assert manifest is not None
    assert manifest.release_id == "release-0001"
    assert manifest.chunk_count == len(chunks)
    assert release == "release-0001"


def test_a_failed_build_leaves_the_previous_release_active(tmp_path):
    from backend.rag.index_release import publish_release, read_manifest

    provider = _provider()
    chunks = _chunks()
    good = lambda _text: [0.1] * provider.dimensions  # noqa: E731
    publish_release(chunks=chunks, provider=provider, embedding_lookup=good,
                    root=tmp_path, release_id="release-0001",
                    documents=_documents())

    def broken(_text):
        raise RuntimeError("embedding service unavailable")

    from backend.rag.ingest import chunk_markdown

    changed = _documents("changed", "content")
    changed_chunks = [c for d in changed for c in chunk_markdown(d)]

    with pytest.raises(RuntimeError):
        publish_release(chunks=changed_chunks, provider=provider,
                        embedding_lookup=broken, root=tmp_path,
                        release_id="release-0002", documents=changed)

    manifest = read_manifest(tmp_path)
    assert manifest is not None
    assert manifest.release_id == "release-0001"


def test_a_rejected_build_leaves_the_previous_release_active(tmp_path):
    """A NaN vector is caught before the manifest switches, not after."""
    from backend.rag.index_release import publish_release, read_manifest

    provider = _provider()
    chunks = _chunks()
    good = lambda _text: [0.1] * provider.dimensions  # noqa: E731
    publish_release(chunks=chunks, provider=provider, embedding_lookup=good,
                    root=tmp_path, release_id="release-0001",
                    documents=_documents())

    # A different corpus forces re-embedding, so the bad vector is actually produced
    # rather than satisfied from the previous release's cache.
    from backend.rag.ingest import chunk_markdown

    changed = _documents("changed", "content")
    changed_chunks = [c for d in changed for c in chunk_markdown(d)]

    with pytest.raises(ValueError, match="finite"):
        publish_release(chunks=changed_chunks, provider=provider,
                        embedding_lookup=lambda _t: [float("inf")] * provider.dimensions,
                        root=tmp_path, release_id="release-0002",
                        documents=changed)

    assert read_manifest(tmp_path).release_id == "release-0001"


def test_a_release_directory_is_not_overwritten_in_place(tmp_path):
    """Each release gets its own directory; the active pointer moves, files do not."""
    from backend.rag.index_release import publish_release

    provider = _provider()
    chunks = _chunks()
    lookup = lambda _text: [0.1] * provider.dimensions  # noqa: E731

    publish_release(chunks=chunks, provider=provider, embedding_lookup=lookup,
                    root=tmp_path, release_id="release-0001", documents=_documents())
    first = (tmp_path / "release-0001").stat().st_mtime_ns

    publish_release(chunks=chunks, provider=provider, embedding_lookup=lookup,
                    root=tmp_path, release_id="release-0002", documents=_documents())

    assert (tmp_path / "release-0001").exists()
    assert (tmp_path / "release-0002").exists()
    assert (tmp_path / "release-0001").stat().st_mtime_ns == first


# --------------------------------------------------------------------------
# incremental reuse
# --------------------------------------------------------------------------

def test_only_changed_chunks_are_re_embedded(tmp_path):
    from backend.rag.index_release import publish_release

    provider = _provider()
    before = _chunks()
    embedded: list[str] = []

    def counting(text):
        embedded.append(text)
        return [0.1] * provider.dimensions

    publish_release(chunks=before, provider=provider, embedding_lookup=counting,
                    root=tmp_path, release_id="release-0001",
                    documents=_documents())
    first_round = len(embedded)

    # Change one document; the other is untouched.
    after_documents = _documents("changed content here", "beta")
    from backend.rag.ingest import chunk_markdown

    after = [chunk for document in after_documents for chunk in chunk_markdown(document)]
    embedded.clear()
    publish_release(chunks=after, provider=provider, embedding_lookup=counting,
                    root=tmp_path, release_id="release-0002",
                    previous_root=tmp_path / "release-0001",
                    documents=after_documents)

    assert first_round == len(before)
    assert 0 < len(embedded) < first_round


def test_a_provider_change_forces_a_full_rebuild(tmp_path):
    from backend.rag.index_release import publish_release

    provider = _provider()
    chunks = _chunks()
    embedded: list[str] = []
    counting = lambda text: (embedded.append(text), [0.1] * provider.dimensions)[1]  # noqa: E731

    publish_release(chunks=chunks, provider=provider, embedding_lookup=counting,
                    root=tmp_path, release_id="release-0001", documents=_documents())
    embedded.clear()

    class OtherProvider:
        provider_name = provider.provider_name
        model_name = "different-model"
        dimensions = provider.dimensions

    publish_release(chunks=chunks, provider=OtherProvider(), embedding_lookup=counting,
                    root=tmp_path, release_id="release-0002",
                    previous_root=tmp_path / "release-0001", documents=_documents())

    assert len(embedded) == len(chunks)
