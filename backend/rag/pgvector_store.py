"""PostgreSQL + pgvector dual-release RAG store with HNSW cosine indexing and GC."""
from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from typing import Any

from backend.infrastructure.postgres.database import PostgresDatabase
from backend.infrastructure.postgres.errors import DatabaseOperationalError
from backend.rag.contracts import (
    CHUNKING_VERSION,
    IndexManifest,
    content_hash,
    corpus_digest,
)

EmbeddingLookup = Callable[[str], list[float]]
HNSW_MAX_DIMENSIONS = 2000


def _provider_identity(provider: Any) -> tuple[str, str]:
    return (
        str(getattr(provider, "provider_name", type(provider).__name__)),
        str(provider.model_name),
    )


def _config_digest_for(provider_name: str, model_name: str, dimensions: int) -> str:
    return content_hash(f"{provider_name}\u0000{model_name}\u0000{dimensions}")


def _format_vector(values: Sequence[float]) -> str:
    formatted: list[str] = []
    for val in values:
        number = float(val)
        if not math.isfinite(number):
            raise ValueError("vector contains a non-finite value")
        formatted.append(f"{number:.8f}")
    return "[" + ",".join(formatted) + "]"


def _parse_vector(raw: Any) -> list[float]:
    if isinstance(raw, (list, tuple)):
        return [float(item) for item in raw]
    text = str(raw).strip()
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [float(part) for part in inner.split(",")]
    raise ValueError("Unsupported stored vector representation")


def _decode_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value is None or value == "":
        return {}
    parsed = json.loads(value)
    return dict(parsed) if isinstance(parsed, dict) else {}


def _validate_vector(vector: Any, *, dimensions: int | None, where: str) -> int:
    if not isinstance(vector, (list, tuple)) or not vector:
        raise ValueError(f"missing vector for {where}")
    width = len(vector)
    if dimensions is not None and width != dimensions:
        raise ValueError(
            f"vector dimension {width} does not match {dimensions} for {where}"
        )
    for value in vector:
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"vector for {where} contains a non-finite value")
    return width


def _chunk_metadata(chunk: dict[str, Any]) -> dict[str, Any]:
    known = {
        "chunk_id",
        "content_hash",
        "document_version",
        "source",
        "heading",
        "text",
        "ordinal",
        "source_url",
        "published_at",
        "reviewed_at",
        "embedding",
    }
    return {k: v for k, v in chunk.items() if k not in known and v is not None}


class PgVectorReleaseStore:
    """Manages immutable dual-version pgvector index releases and atomic pointer swaps."""

    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def read_manifest(self) -> IndexManifest | None:
        try:
            with self.database.connection() as connection:
                row = connection.execute(
                    """
                    SELECT r.release_id, r.corpus_digest, r.chunking_version,
                           r.embedding_provider, r.embedding_model,
                           r.embedding_dimensions, r.chunk_count
                    FROM rag_active_pointer AS p
                    JOIN rag_index_releases AS r ON r.release_id = p.active_release_id
                    WHERE p.slot = 'default'
                    """
                ).fetchone()
        except DatabaseOperationalError as error:
            if error.sqlstate in {"42P01", "3F000"} or "does not exist" in str(error).casefold():
                return None
            raise
        if row is None:
            return None
        return IndexManifest(
            schema_version=1,
            release_id=row["release_id"],
            corpus_digest=row["corpus_digest"],
            chunking_version=row["chunking_version"],
            embedding_provider=row["embedding_provider"],
            embedding_model=row["embedding_model"],
            embedding_dimensions=int(row["embedding_dimensions"]),
            config_digest=_config_digest_for(
                row["embedding_provider"],
                row["embedding_model"],
                int(row["embedding_dimensions"]),
            ),
            chunk_count=int(row["chunk_count"]),
        )

    def pointer_state(self) -> dict[str, str | None] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT active_release_id, previous_release_id
                FROM rag_active_pointer
                WHERE slot = 'default'
                """
            ).fetchone()
        if row is None:
            return None
        return {
            "active_release_id": row["active_release_id"],
            "previous_release_id": row["previous_release_id"],
        }

    def list_releases(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT release_id, status, corpus_digest, chunking_version,
                       embedding_provider, embedding_model, embedding_dimensions,
                       chunk_count, created_at, activated_at, retired_at
                FROM rag_index_releases
                ORDER BY created_at ASC, release_id ASC
                """
            ).fetchall()
        return [
            {
                "release_id": row["release_id"],
                "status": row["status"],
                "corpus_digest": row["corpus_digest"],
                "chunking_version": row["chunking_version"],
                "embedding_provider": row["embedding_provider"],
                "embedding_model": row["embedding_model"],
                "embedding_dimensions": int(row["embedding_dimensions"]),
                "chunk_count": int(row["chunk_count"]),
                "created_at": row["created_at"],
                "activated_at": row["activated_at"],
                "retired_at": row["retired_at"],
            }
            for row in rows
        ]

    def next_release_id(self) -> str:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT release_id FROM rag_index_releases"
            ).fetchall()
        return self._next_release_num([row["release_id"] for row in rows])

    @staticmethod
    def _next_release_num(existing_ids: Sequence[str]) -> str:
        next_num = 0
        for rid in existing_ids:
            if isinstance(rid, str) and rid.startswith("release-"):
                try:
                    next_num = max(next_num, int(rid.split("-", 1)[1]) + 1)
                except (IndexError, ValueError):
                    continue
        return f"release-{next_num:04d}"

    def previous_vectors(
        self,
        provider: Any,
        *,
        previous_release_id: str | None = None,
    ) -> dict[str, list[float]]:
        provider_name, model_name = _provider_identity(provider)
        target_dims = int(provider.dimensions)
        with self.database.connection() as connection:
            if previous_release_id is None:
                ptr = connection.execute(
                    "SELECT active_release_id FROM rag_active_pointer WHERE slot = 'default'"
                ).fetchone()
                if ptr is None:
                    return {}
                previous_release_id = ptr["active_release_id"]
            rel = connection.execute(
                """
                SELECT chunking_version, embedding_provider, embedding_model, embedding_dimensions
                FROM rag_index_releases
                WHERE release_id = ?
                """,
                (previous_release_id,),
            ).fetchone()
            if rel is None:
                return {}
            if (
                rel["chunking_version"] != CHUNKING_VERSION
                or rel["embedding_provider"] != provider_name
                or rel["embedding_model"] != model_name
                or int(rel["embedding_dimensions"]) != target_dims
            ):
                return {}
            rows = connection.execute(
                "SELECT content_hash, embedding::text AS vec FROM rag_chunks WHERE release_id = ?",
                (previous_release_id,),
            ).fetchall()
        vectors: dict[str, list[float]] = {}
        for row in rows:
            try:
                vectors[row["content_hash"]] = _parse_vector(row["vec"])
            except (TypeError, ValueError):
                continue
        return vectors

    def publish_release(
        self,
        *,
        chunks: list[dict[str, Any]],
        provider: Any,
        embedding_lookup: EmbeddingLookup,
        documents: list[dict[str, Any]],
        release_id: str | None = None,
        previous_release_id: str | None = None,
        keep_previous: int = 1,
    ) -> str:
        ids = [chunk["chunk_id"] for chunk in chunks]
        if len(ids) != len(set(ids)):
            raise ValueError("chunk ids must be unique within a release")
        for chunk in chunks:
            if not chunk.get("text"):
                raise ValueError("a chunk must carry text")
            if chunk.get("content_hash") != content_hash(chunk["text"]):
                raise ValueError("chunk content_hash does not match its text")

        reuse = self.previous_vectors(provider, previous_release_id=previous_release_id)
        provider_name, model_name = _provider_identity(provider)

        prepared_rows: list[tuple[dict[str, Any], list[float]]] = []
        dimensions: int | None = int(getattr(provider, "dimensions", 0) or 0) or None
        for chunk in chunks:
            cached = reuse.get(chunk["content_hash"])
            vector = list(cached) if cached is not None else embedding_lookup(chunk["text"])
            width = _validate_vector(vector, dimensions=dimensions, where=chunk["chunk_id"])
            dimensions = width if dimensions is None else dimensions
            prepared_rows.append((chunk, list(vector)))

        if dimensions is None:
            dimensions = int(provider.dimensions)

        computed_digest = corpus_digest(documents)

        with self.database.transaction() as connection:
            if release_id is None:
                existing_rows = connection.execute(
                    "SELECT release_id FROM rag_index_releases FOR UPDATE"
                ).fetchall()
                release_id = self._next_release_num([r["release_id"] for r in existing_rows])

            connection.execute(
                """
                INSERT INTO rag_index_releases (
                    release_id, status, corpus_digest, chunking_version,
                    embedding_provider, embedding_model, embedding_dimensions,
                    chunk_count
                )
                VALUES (?, 'building', ?, ?, ?, ?, ?, ?)
                """,
                (
                    release_id,
                    computed_digest,
                    CHUNKING_VERSION,
                    provider_name,
                    model_name,
                    dimensions,
                    len(prepared_rows),
                ),
            )

            for chunk, vector in prepared_rows:
                metadata = _chunk_metadata(chunk)
                connection.execute(
                    """
                    INSERT INTO rag_chunks (
                        release_id, chunk_id, content_hash, document_version,
                        source, heading, text, ordinal,
                        source_url, published_at, reviewed_at,
                        metadata_json, embedding
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?::vector)
                    """,
                    (
                        release_id,
                        chunk["chunk_id"],
                        chunk["content_hash"],
                        chunk["document_version"],
                        chunk["source"],
                        chunk["heading"],
                        chunk["text"],
                        int(chunk["ordinal"]),
                        chunk.get("source_url"),
                        chunk.get("published_at"),
                        chunk.get("reviewed_at"),
                        json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                        _format_vector(vector),
                    ),
                )

            if dimensions <= HNSW_MAX_DIMENSIONS:
                connection.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_rag_chunks_hnsw_d{dimensions}
                    ON rag_chunks
                    USING hnsw ((embedding::vector({dimensions})) vector_cosine_ops)
                    WHERE vector_dims(embedding) = {dimensions}
                    """
                )

            pointer = connection.execute(
                """
                SELECT active_release_id, previous_release_id
                FROM rag_active_pointer
                WHERE slot = 'default'
                FOR UPDATE
                """
            ).fetchone()
            old_active = pointer["active_release_id"] if pointer is not None else None
            if old_active is not None:
                connection.execute(
                    """
                    UPDATE rag_index_releases
                    SET status = 'retired', retired_at = NOW()
                    WHERE release_id = ?
                    """,
                    (old_active,),
                )
            connection.execute(
                """
                UPDATE rag_index_releases
                SET status = 'active', activated_at = NOW()
                WHERE release_id = ?
                """,
                (release_id,),
            )
            connection.execute(
                """
                INSERT INTO rag_active_pointer (
                    slot, active_release_id, previous_release_id, switched_at
                )
                VALUES ('default', ?, ?, NOW())
                ON CONFLICT (slot) DO UPDATE SET
                    active_release_id = excluded.active_release_id,
                    previous_release_id = excluded.previous_release_id,
                    switched_at = NOW()
                """,
                (release_id, old_active),
            )
            self._cleanup_retired_in_tx(connection, keep_previous=keep_previous)
        return release_id

    def cleanup_retired_releases(self, *, keep_previous: int = 1) -> int:
        with self.database.transaction() as connection:
            return self._cleanup_retired_in_tx(connection, keep_previous=keep_previous)

    def _cleanup_retired_in_tx(self, connection, *, keep_previous: int) -> int:
        keep_count = max(0, int(keep_previous))
        pointer = connection.execute(
            """
            SELECT active_release_id, previous_release_id
            FROM rag_active_pointer
            WHERE slot = 'default'
            FOR UPDATE
            """
        ).fetchone()
        protected: set[str] = set()
        if pointer is not None:
            if pointer["active_release_id"]:
                protected.add(pointer["active_release_id"])
            if keep_count == 0 and pointer["previous_release_id"] is not None:
                connection.execute(
                    """
                    UPDATE rag_active_pointer
                    SET previous_release_id = NULL
                    WHERE slot = 'default'
                    """
                )
            elif pointer["previous_release_id"]:
                protected.add(pointer["previous_release_id"])

        retired_rows = connection.execute(
            """
            SELECT release_id
            FROM rag_index_releases
            WHERE status = 'retired'
            ORDER BY retired_at DESC NULLS LAST, created_at DESC, release_id DESC
            """
        ).fetchall()
        retained_retired = [row["release_id"] for row in retired_rows[:keep_count]]
        protected.update(retained_retired)

        all_rows = connection.execute(
            """
            SELECT release_id
            FROM rag_index_releases
            WHERE status IN ('retired', 'failed')
            """
        ).fetchall()
        victims = [row["release_id"] for row in all_rows if row["release_id"] not in protected]
        deleted = 0
        for victim in victims:
            cursor = connection.execute(
                "DELETE FROM rag_index_releases WHERE release_id = ?",
                (victim,),
            )
            deleted += cursor.rowcount
        return deleted

    def rollback_release(self) -> str:
        with self.database.transaction() as connection:
            pointer = connection.execute(
                """
                SELECT active_release_id, previous_release_id
                FROM rag_active_pointer
                WHERE slot = 'default'
                FOR UPDATE
                """
            ).fetchone()
            if pointer is None or pointer["previous_release_id"] is None:
                raise ValueError("No previous release available for rollback")
            current_active = pointer["active_release_id"]
            restored_release = pointer["previous_release_id"]
            connection.execute(
                """
                UPDATE rag_index_releases
                SET status = 'retired', retired_at = NOW()
                WHERE release_id = ?
                """,
                (current_active,),
            )
            connection.execute(
                """
                UPDATE rag_index_releases
                SET status = 'active', activated_at = NOW(), retired_at = NULL
                WHERE release_id = ?
                """,
                (restored_release,),
            )
            connection.execute(
                """
                UPDATE rag_active_pointer
                SET active_release_id = ?,
                    previous_release_id = ?,
                    switched_at = NOW()
                WHERE slot = 'default'
                """,
                (restored_release, current_active),
            )
        return restored_release

    def load_chunks(self, release_id: str | None = None) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            target_id = release_id
            if target_id is None:
                ptr = connection.execute(
                    "SELECT active_release_id FROM rag_active_pointer WHERE slot = 'default'"
                ).fetchone()
                if ptr is None:
                    return []
                target_id = ptr["active_release_id"]
            rows = connection.execute(
                """
                SELECT chunk_id, content_hash, document_version, source, heading,
                       text, ordinal, source_url, published_at, reviewed_at,
                       metadata_json
                FROM rag_chunks
                WHERE release_id = ?
                ORDER BY source ASC, ordinal ASC, chunk_id ASC
                """,
                (target_id,),
            ).fetchall()
        chunks: list[dict[str, Any]] = []
        for row in rows:
            extra = _decode_json(row["metadata_json"])
            chunk = {
                **extra,
                "chunk_id": row["chunk_id"],
                "content_hash": row["content_hash"],
                "document_version": row["document_version"],
                "source": row["source"],
                "heading": row["heading"],
                "text": row["text"],
                "ordinal": int(row["ordinal"]),
            }
            if row["source_url"] is not None:
                chunk["source_url"] = row["source_url"]
            if row["published_at"] is not None:
                chunk["published_at"] = row["published_at"]
            if row["reviewed_at"] is not None:
                chunk["reviewed_at"] = row["reviewed_at"]
            chunks.append(chunk)
        return chunks

    def search_vectors(
        self,
        query_vector: Sequence[float],
        *,
        top_k: int,
        release_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if top_k <= 0:
            return []
        dims = len(query_vector)
        if dims <= 0:
            return []
        vec_literal = _format_vector(query_vector)
        with self.database.connection() as connection:
            target_id = release_id
            if target_id is None:
                ptr = connection.execute(
                    "SELECT active_release_id FROM rag_active_pointer WHERE slot = 'default'"
                ).fetchone()
                if ptr is None:
                    return []
                target_id = ptr["active_release_id"]
            rows = connection.execute(
                f"""
                SELECT chunk_id, content_hash, document_version, source, heading,
                       text, ordinal, source_url, published_at, reviewed_at,
                       metadata_json,
                       1.0 - ((embedding::vector({dims})) <=> (?::vector({dims}))) AS score
                FROM rag_chunks
                WHERE release_id = ? AND vector_dims(embedding) = {dims}
                ORDER BY (embedding::vector({dims})) <=> (?::vector({dims})) ASC, chunk_id ASC
                LIMIT ?
                """,
                (vec_literal, target_id, vec_literal, int(top_k)),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            raw_score = row["score"]
            score = (
                float(raw_score)
                if raw_score is not None and math.isfinite(float(raw_score))
                else 0.0
            )
            extra = _decode_json(row["metadata_json"])
            item = {
                **extra,
                "chunk_id": row["chunk_id"],
                "content_hash": row["content_hash"],
                "document_version": row["document_version"],
                "source": row["source"],
                "heading": row["heading"],
                "text": row["text"],
                "ordinal": int(row["ordinal"]),
                "score": score,
            }
            if row["source_url"] is not None:
                item["source_url"] = row["source_url"]
            if row["published_at"] is not None:
                item["published_at"] = row["published_at"]
            if row["reviewed_at"] is not None:
                item["reviewed_at"] = row["reviewed_at"]
            results.append(item)
        return results
