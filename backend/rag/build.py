"""CLI entry point to build and publish the local RAG index outside the request path.

Usage:
    python -m backend.rag.build [--index-path <path>]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.config import get_settings
from backend.rag.retriever import build_knowledge_index
from backend.rag.vector_store import build_embedding_provider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and publish the FitLife knowledge index")
    parser.add_argument("--index-path", type=Path, default=None)
    args = parser.parse_args(argv)
    settings = get_settings()
    provider = build_embedding_provider(settings=settings)
    index_path = args.index_path or settings.vector_index_path
    release_id = build_knowledge_index(provider=provider, index_path=index_path)
    print(
        json.dumps(
            {
                "release_id": release_id,
                "provider": provider.provider_name,
                "model": provider.model_name,
                "index_path": str(index_path),
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
