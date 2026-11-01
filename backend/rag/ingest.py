"""Markdown ingestion: split without losing text, and give every chunk an identity.

R0 recorded the defect this replaces: ``flush()`` joined the buffer and returned
``text[:max_chars]``, so any block over the cap lost its tail instead of continuing.
The corpus's long-line document proves it - a 1070-character paragraph came back as 900.

Three properties are now load bearing:

* **nothing is dropped** - every non-whitespace character of the body appears in some
  chunk, and no chunk exceeds the cap;
* **structure survives** - a continuation chunk keeps the heading it started under, and
  ordinals run contiguously from zero;
* **identity is position, version is hash** - a chunk id stays the same when the text at
  that position is edited, so an edit shows up as a hash change rather than as every id
  moving.

Provenance is passed through only when the document declares it. A field that was never
declared stays ``None``: inventing a publication date would invent authority.
"""
from __future__ import annotations

from pathlib import Path

from backend.config import get_settings
from backend.rag.contracts import (
    CHUNKING_VERSION,
    chunk_id,
    content_hash,
    document_version,
)

# Sentence and clause terminators used to prefer a natural split point over a hard cut.
_SOFT_BREAKS = frozenset("，。；！？、：,.;!?:）)】」》 \t")
# How far back from the cap a soft break may be taken. Below this we prefer a full
# window: shortening a chunk too much wastes the reader's context.
_SOFT_BREAK_FLOOR = 0.8


def load_markdown_documents(base_dir: str | Path | None = None) -> list[dict]:
    root = Path(base_dir) if base_dir else get_settings().knowledge_base_dir
    documents: list[dict] = []
    for path in sorted(root.glob("*.md")):
        documents.append({"source": path.name, "text": path.read_text(encoding="utf-8")})
    return documents


def _sections(text: str) -> list[tuple[str, list[str]]]:
    """Split into (heading, lines) pairs, keeping the order they appear in."""
    sections: list[tuple[str, list[str]]] = []
    heading = "Overview"
    lines: list[str] = []
    seen_heading = False

    for line in text.splitlines():
        if line.startswith("#"):
            if seen_heading or any(item.strip() for item in lines):
                sections.append((heading, lines))
            heading = line.lstrip("#").strip() or "Overview"
            lines = []
            seen_heading = True
        else:
            lines.append(line)
    sections.append((heading, lines))
    return sections


def _soft_cut(text: str, limit: int) -> int:
    """Where to cut a line that is longer than ``limit``.

    Prefer the last terminator inside the window; fall back to the hard boundary. Either
    way the cut position only decides *where* the text is divided - no character is
    discarded.
    """
    window = text[:limit]
    floor = int(limit * _SOFT_BREAK_FLOOR)
    for index in range(len(window) - 1, floor - 1, -1):
        if window[index] in _SOFT_BREAKS:
            return index + 1
    return limit


def _pieces(line: str, limit: int) -> list[str]:
    """Break one line into pieces that each fit ``limit`` characters."""
    if len(line) <= limit:
        return [line]
    out: list[str] = []
    rest = line
    while len(rest) > limit:
        cut = _soft_cut(rest, limit)
        out.append(rest[:cut])
        rest = rest[cut:]
    if rest:
        out.append(rest)
    return out


def _assemble(pieces: list[str], max_chars: int) -> list[str]:
    """Pack pieces into chunks no larger than ``max_chars``."""
    chunks: list[str] = []
    buffer: list[str] = []
    for piece in pieces:
        candidate = buffer + [piece]
        if buffer and len("\n".join(candidate)) > max_chars:
            chunks.append("\n".join(buffer))
            buffer = [piece]
        else:
            buffer = candidate
    if buffer:
        chunks.append("\n".join(buffer))
    return [chunk for chunk in chunks if chunk.strip()]


def chunk_markdown(document: dict, max_chars: int = 900) -> list[dict]:
    """Split a markdown document into identified, complete chunks."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    source = str(document["source"])
    text = str(document["text"])
    version = document_version(text)
    provenance = {
        "source_url": document.get("source_url"),
        "published_at": document.get("published_at"),
        "reviewed_at": document.get("reviewed_at"),
    }

    chunks: list[dict] = []
    ordinal = 0
    for heading, lines in _sections(text):
        pieces = [piece for line in lines for piece in _pieces(line, max_chars)]
        for body in _assemble(pieces, max_chars):
            chunks.append({
                "chunk_id": chunk_id(source, heading, ordinal),
                "content_hash": content_hash(body),
                "document_version": version,
                "chunking_version": CHUNKING_VERSION,
                "source": source,
                "heading": heading,
                "text": body,
                "ordinal": ordinal,
                **provenance,
            })
            ordinal += 1
    return chunks


def load_knowledge_chunks(base_dir: str | Path | None = None) -> list[dict]:
    chunks: list[dict] = []
    for document in load_markdown_documents(base_dir):
        chunks.extend(chunk_markdown(document))
    return chunks


def ensure_chunk_identity(chunks: list[dict]) -> list[dict]:
    """Fill in the identity fields a chunk needs to be cited and invalidated.

    Chunks produced by ``chunk_markdown`` already carry all of these. A hand-built list
    (a test double, or a caller parsing its own source) may not, and rather than
    maintaining a second code path that skips validity checks, the identity is derived
    here deterministically. Nothing about the text changes.
    """
    seen: dict[tuple[str, str], int] = {}
    output: list[dict] = []
    for chunk in chunks:
        source = str(chunk.get("source", ""))
        heading = str(chunk.get("heading") or "Overview")
        text = str(chunk.get("text", ""))
        key = (source, heading)
        ordinal = chunk.get("ordinal")
        if ordinal is None:
            ordinal = seen.get(key, 0)
        seen[key] = max(seen.get(key, 0), int(ordinal) + 1)
        output.append({
            **chunk,
            "source": source,
            "heading": heading,
            "ordinal": int(ordinal),
            "chunk_id": chunk.get("chunk_id") or chunk_id(source, heading, int(ordinal)),
            "content_hash": chunk.get("content_hash") or content_hash(text),
            "document_version": chunk.get("document_version") or document_version(text),
            "chunking_version": chunk.get("chunking_version") or CHUNKING_VERSION,
        })
    return output
