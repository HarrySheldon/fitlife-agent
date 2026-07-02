from __future__ import annotations

from pathlib import Path

from backend.config import get_settings


def load_markdown_documents(base_dir: str | Path | None = None) -> list[dict]:
    root = Path(base_dir) if base_dir else get_settings().knowledge_base_dir
    documents: list[dict] = []
    for path in sorted(root.glob("*.md")):
        documents.append({"source": path.name, "text": path.read_text(encoding="utf-8")})
    return documents


def chunk_markdown(document: dict, max_chars: int = 900) -> list[dict]:
    chunks: list[dict] = []
    source = document["source"]
    heading = "Overview"
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        text = "\n".join(buffer).strip()
        if text:
            chunks.append({"source": source, "heading": heading, "text": text[:max_chars]})
        buffer.clear()

    for line in document["text"].splitlines():
        if line.startswith("#"):
            flush()
            heading = line.lstrip("#").strip() or "Overview"
        else:
            buffer.append(line)
            if sum(len(item) for item in buffer) >= max_chars:
                flush()
    flush()
    return chunks


def load_knowledge_chunks(base_dir: str | Path | None = None) -> list[dict]:
    chunks: list[dict] = []
    for document in load_markdown_documents(base_dir):
        chunks.extend(chunk_markdown(document))
    return chunks
