"""CLI entry point to build and publish the PostgreSQL pgvector RAG index.

Usage:
    python -m backend.rag.build [--database-url <url>] [--schema <schema>]
"""
from __future__ import annotations

import argparse
import json

from backend.config import get_settings
from backend.infrastructure.postgres.database import PostgresDatabase
from backend.infrastructure.postgres.runtime import ensure_database_ready
from backend.rag.retriever import build_knowledge_index
from backend.rag.vector_store import build_embedding_provider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and publish the FitLife pgvector knowledge index")
    parser.add_argument("--database-url", type=str, default=None)
    parser.add_argument("--schema", type=str, default=None)
    args = parser.parse_args(argv)
    settings = get_settings()
    database = PostgresDatabase(
        args.database_url or settings.database_url,
        schema=args.schema or settings.database_schema,
    )
    ensure_database_ready(database)
    provider = build_embedding_provider(settings=settings)
    release_id = build_knowledge_index(provider=provider, database=database)
    print(
        json.dumps(
            {
                "release_id": release_id,
                "provider": provider.provider_name,
                "model": provider.model_name,
                "schema": database.target_schema,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
