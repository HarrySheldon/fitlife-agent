"""Index releases: validity by manifest, publication by atomic pointer swap.

Two rules govern this module.

**Validity is proved, not guessed.** R0's loader compared an embedding model name and a
chunk count, which is a guess derived from shape - and it was wrong: editing a document
without changing how many chunks it produced kept serving the old text. Validity is now
decided by comparing a manifest against the corpus actually being indexed: corpus digest,
chunking version, provider, model, dimensions and chunk count.

**Publication never mutates a live release.** A new index is written into its own
directory, validated there, and only then does the active pointer move. A build that
raises, or produces a vector that cannot be trusted, leaves the previous release in
place - which is the difference between "the rebuild failed" and "retrieval is broken".

Incremental reuse is deliberately narrow: a vector is reused only when the embedding
configuration is unchanged *and* the chunk's content hash is unchanged. Anything else is
re-embedded, because a reused vector from a different configuration is not the same
vector.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Callable

from backend.rag.contracts import (
    CHUNKING_VERSION,
    IndexManifest,
    content_hash,
    corpus_digest,
)

MANIFEST_NAME = "manifest.json"
INDEX_NAME = "index.json"

EmbeddingLookup = Callable[[str], list[float]]


def _provider_identity(provider) -> tuple[str, str]:
    """Provider and model name, tolerating a provider that only declares a model.

    A test double that says nothing about its provider is treated as its own provider
    (its type name), which is the conservative choice: it will never be mistaken for
    the real provider and therefore never share an index with it.
    """
    return (
        str(getattr(provider, "provider_name", type(provider).__name__)),
        str(provider.model_name),
    )


def _config_digest(provider) -> str:
    provider_name, model_name = _provider_identity(provider)
    material = f"{provider_name}\u0000{model_name}\u0000{provider.dimensions}"
    return content_hash(material)


def index_is_valid(manifest: IndexManifest, *, provider, documents: list[dict],
                   chunk_count: int) -> bool:
    """Is this manifest still a correct description of the index we would build now?"""
    provider_name, model_name = _provider_identity(provider)
    return (
        manifest.corpus_digest == corpus_digest(documents)
        and manifest.chunking_version == CHUNKING_VERSION
        and manifest.embedding_provider == provider_name
        and manifest.embedding_model == model_name
        and manifest.embedding_dimensions == provider.dimensions
        and manifest.chunk_count == chunk_count
    )


def manifest_path(root: str | Path) -> Path:
    return Path(root) / MANIFEST_NAME


def read_manifest(root: str | Path) -> IndexManifest | None:
    """The active manifest, or ``None`` when nothing has been published yet."""
    path = manifest_path(root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        return IndexManifest.model_validate(payload)
    except Exception:
        # A corrupt pointer is not a usable release. Report absence rather than
        # raising on every caller that merely asks what is published.
        return None


def _previous_vectors(previous_root: Path | None, provider) -> dict[str, list[float]]:
    """Content-hash keyed vectors from the previous release, if it is comparable."""
    if previous_root is None:
        return {}
    path = Path(previous_root) / INDEX_NAME
    manifest = read_manifest(previous_root)
    if not path.exists() or manifest is None:
        return {}
    provider_name, model_name = _provider_identity(provider)
    if (manifest.chunking_version != CHUNKING_VERSION
            or manifest.embedding_provider != provider_name
            or manifest.embedding_model != model_name
            or manifest.embedding_dimensions != provider.dimensions):
        # A different configuration produces different vectors; reusing them would
        # silently mix two embedding spaces in one index.
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    vectors: dict[str, list[float]] = {}
    for entry in payload.get("entries", []):
        try:
            vectors[entry["content_hash"]] = list(entry["embedding"])
        except (KeyError, TypeError):
            continue
    return vectors


def _validate_vector(vector, *, dimensions: int | None, where: str) -> int:
    if not isinstance(vector, list) or not vector:
        raise ValueError(f"missing vector for {where}")
    width = len(vector)
    if dimensions is not None and width != dimensions:
        raise ValueError(f"vector dimension {width} does not match {dimensions} for {where}")
    for value in vector:
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"vector for {where} contains a non-finite value")
    return width


def publish_release(*, chunks: list[dict], provider, embedding_lookup: EmbeddingLookup,
                    root: str | Path, release_id: str, documents: list[dict],
                    previous_root: str | Path | None = None) -> str:
    """Build, validate and atomically activate a release.

    Returns the release id that is now active. Raises before the pointer moves if
    anything about the new index cannot be trusted.
    """
    root = Path(root)
    ids = [chunk["chunk_id"] for chunk in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("chunk ids must be unique within a release")
    for chunk in chunks:
        if not chunk.get("text"):
            raise ValueError("a chunk must carry text")
        if chunk.get("content_hash") != content_hash(chunk["text"]):
            raise ValueError("chunk content_hash does not match its text")

    reuse = _previous_vectors(Path(previous_root) if previous_root else _active_root(root),
                              provider)

    entries: list[dict] = []
    dimensions: int | None = None
    for chunk in chunks:
        cached = reuse.get(chunk["content_hash"])
        if cached is not None:
            vector = list(cached)
        else:
            vector = embedding_lookup(chunk["text"])
        width = _validate_vector(vector, dimensions=dimensions, where=chunk["chunk_id"])
        dimensions = width if dimensions is None else dimensions
        entries.append({
            "chunk_id": chunk["chunk_id"],
            "content_hash": chunk["content_hash"],
            "document_version": chunk["document_version"],
            "source": chunk["source"],
            "heading": chunk["heading"],
            "text": chunk["text"],
            "ordinal": chunk["ordinal"],
            "source_url": chunk.get("source_url"),
            "published_at": chunk.get("published_at"),
            "reviewed_at": chunk.get("reviewed_at"),
            "embedding": vector,
        })

    release_dir = root / release_id
    release_dir.mkdir(parents=True, exist_ok=True)
    provider_name, model_name = _provider_identity(provider)
    payload = {
        "schema_version": 1,
        "chunking_version": CHUNKING_VERSION,
        "embedding_provider": provider_name,
        "embedding_model": model_name,
        "embedding_dimensions": dimensions or provider.dimensions,
        "entries": entries,
    }
    (release_dir / INDEX_NAME).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    manifest = IndexManifest(
        schema_version=1,
        release_id=release_id,
        corpus_digest=corpus_digest(documents),
        chunking_version=CHUNKING_VERSION,
        embedding_provider=provider_name,
        embedding_model=model_name,
        embedding_dimensions=dimensions or provider.dimensions,
        config_digest=_config_digest(provider),
        chunk_count=len(chunks),
    )
    (release_dir / MANIFEST_NAME).write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8")

    # Only now does the active pointer move, and it moves atomically.
    _activate(root, manifest)
    return release_id


def _active_root(root: Path) -> Path | None:
    manifest = read_manifest(root)
    if manifest is None:
        return None
    candidate = root / manifest.release_id
    return candidate if candidate.exists() else None


def _activate(root: Path, manifest: IndexManifest) -> None:
    """Replace the active manifest in one filesystem operation."""
    root.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=root, prefix=".manifest-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(manifest.model_dump_json(indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, manifest_path(root))
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def load_release(root: str | Path) -> tuple[IndexManifest, dict] | None:
    """The active release's manifest and index payload, or ``None``."""
    root = Path(root)
    manifest = read_manifest(root)
    if manifest is None:
        return None
    path = root / manifest.release_id / INDEX_NAME
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return manifest, payload
