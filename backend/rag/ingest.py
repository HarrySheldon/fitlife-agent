"""Document ingestion: Markdown, frontmatter, structured tables, PDFs, overlap & identity.

Three invariants stay preserved from R1:
* ``chunk_markdown(..., overlap_ratio=0.0)`` loses zero characters and never exceeds ``max_chars``;
* section structure survives across continuation chunks (including repeating Markdown table headers);
* ``chunk_id`` identifies position while ``content_hash`` versions the chunk body text.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from backend.config import get_settings
from backend.rag.contextual import apply_contextual_prefixes, build_context_prefix_generator
from backend.rag.contracts import (
    CHUNKING_VERSION,
    chunk_id,
    content_hash,
    document_version,
)
from backend.rag.parsers import (
    infer_domain_from_source,
    load_document_from_path,
    parse_frontmatter,
    split_markdown_blocks,
)

# Sentence and clause terminators used to prefer a natural split point over a hard cut.
_SOFT_BREAKS = frozenset("，。；！？、：,.;!?:）)】」》 \t\n")
# How far back from the cap a soft break may be taken.
_SOFT_BREAK_FLOOR = 0.8


def load_markdown_documents(base_dir: str | Path | None = None) -> list[dict]:
    """Load sorted Markdown and PDF knowledge base documents with optional frontmatter."""
    root = Path(base_dir) if base_dir else get_settings().knowledge_base_dir
    paths = sorted([*root.glob("*.md"), *root.glob("*.pdf")], key=lambda p: p.name)
    return [load_document_from_path(path) for path in paths]


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
    window = text[:limit]
    floor = int(limit * _SOFT_BREAK_FLOOR)
    for index in range(len(window) - 1, floor - 1, -1):
        if window[index] in _SOFT_BREAKS:
            return index + 1
    return limit


def _pieces(line: str, limit: int) -> list[str]:
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


def _overlap_tail(text: str, budget: int) -> str:
    """Take up to ``budget`` trailing chars snapped forward to a soft break when possible."""
    if budget <= 0 or not text:
        return ""
    if len(text) <= budget:
        return text.strip()
    start = len(text) - budget
    for idx in range(start, len(text)):
        if text[idx] in _SOFT_BREAKS:
            candidate = text[idx + 1 :].strip()
            if candidate:
                return candidate
    return text[start:].strip()


def _apply_prose_overlap(chunks: list[str], *, max_chars: int, overlap_ratio: float) -> list[str]:
    if overlap_ratio <= 0 or len(chunks) <= 1:
        return chunks
    target_overlap = int(max_chars * overlap_ratio)
    if target_overlap < 8:
        return chunks
    out = [chunks[0]]
    for idx in range(1, len(chunks)):
        body = chunks[idx]
        room = max_chars - len(body) - 1
        if room >= 12:
            tail = _overlap_tail(chunks[idx - 1], min(target_overlap, room))
            if tail and not body.startswith(tail):
                merged = f"{tail}\n{body}"
                if len(merged) <= max_chars:
                    out.append(merged)
                    continue
        out.append(body)
    return out


def _assemble_table(table_lines: list[str], max_chars: int) -> list[str]:
    """Split a Markdown pipe-table while repeating its header + separator row."""
    full = "\n".join(table_lines)
    if len(full) <= max_chars or len(table_lines) <= 2:
        return [full] if full.strip() else []
    header = table_lines[0]
    separator = table_lines[1]
    prefix = f"{header}\n{separator}"
    if len(prefix) >= max_chars:
        pieces = [piece for line in table_lines for piece in _pieces(line, max_chars)]
        return _assemble(pieces, max_chars)

    chunks: list[str] = []
    rows = table_lines[2:]
    buf: list[str] = [header, separator]
    for row in rows:
        candidate = "\n".join([*buf, row])
        if len(candidate) > max_chars and len(buf) > 2:
            chunks.append("\n".join(buf))
            buf = [header, separator, row]
        elif len("\n".join([header, separator, row])) > max_chars:
            if len(buf) > 2:
                chunks.append("\n".join(buf))
            chunks.extend(_assemble(_pieces(row, max_chars), max_chars))
            buf = [header, separator]
        else:
            buf.append(row)
    if len(buf) > 2:
        chunks.append("\n".join(buf))
    return chunks


def chunk_markdown(
    document: dict,
    max_chars: int = 900,
    *,
    overlap_ratio: float = 0.0,
) -> list[dict]:
    """Split a Markdown/PDF document into identified chunks with optional overlap & tables.

    Defaults to ``overlap_ratio=0.0`` so direct callers checking exact lossless reassembly
    keep identical behavior while ``load_knowledge_chunks`` applies configured sliding overlap.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if not 0.0 <= overlap_ratio < 0.8:
        raise ValueError("overlap_ratio must be in [0.0, 0.8)")

    source = str(document["source"])
    raw_text = str(document["text"])
    frontmatter, body_text = parse_frontmatter(raw_text)
    version = document_version(raw_text)

    domain = document.get("domain") or frontmatter.get("domain") or infer_domain_from_source(source)
    base_doc_type = document.get("doc_type") or frontmatter.get("doc_type") or "markdown"
    provenance = {
        "source_url": document.get("source_url", frontmatter.get("source_url")),
        "published_at": document.get("published_at", frontmatter.get("published_at")),
        "reviewed_at": document.get("reviewed_at", frontmatter.get("reviewed_at")),
        "valid_from": document.get("valid_from", frontmatter.get("valid_from")),
        "expires_at": document.get("expires_at", frontmatter.get("expires_at")),
        "policy_version": document.get("policy_version", frontmatter.get("policy_version")),
        "domain": domain,
    }

    chunks: list[dict] = []
    ordinal = 0
    for heading, lines in _sections(body_text):
        for block_kind, block_lines in split_markdown_blocks(lines):
            if block_kind == "table":
                bodies = _assemble_table(block_lines, max_chars)
                doc_type = "table"
            else:
                pieces = [piece for line in block_lines for piece in _pieces(line, max_chars)]
                bodies = _apply_prose_overlap(
                    _assemble(pieces, max_chars),
                    max_chars=max_chars,
                    overlap_ratio=overlap_ratio,
                )
                doc_type = base_doc_type
            for body in bodies:
                chunks.append({
                    "chunk_id": chunk_id(source, heading, ordinal),
                    "content_hash": content_hash(body),
                    "document_version": version,
                    "chunking_version": CHUNKING_VERSION,
                    "source": source,
                    "heading": heading,
                    "text": body,
                    "ordinal": ordinal,
                    "doc_type": doc_type,
                    **{k: v for k, v in provenance.items() if k in {"source_url", "published_at", "reviewed_at"} or v is not None},
                })
                ordinal += 1
    return chunks


def load_knowledge_chunks(
    base_dir: str | Path | None = None,
    *,
    max_chars: int = 900,
    overlap_ratio: float | None = None,
    contextual_mode: str | None = None,
    cached_prefixes: Mapping[tuple[str, str], str] | None = None,
) -> list[dict]:
    settings = get_settings()
    effective_overlap = (
        settings.rag_chunk_overlap_ratio if overlap_ratio is None else float(overlap_ratio)
    )
    documents = load_markdown_documents(base_dir)
    chunks: list[dict] = []
    for document in documents:
        chunks.extend(chunk_markdown(document, max_chars=max_chars, overlap_ratio=effective_overlap))

    mode = contextual_mode if contextual_mode is not None else settings.rag_contextual_prefix_mode
    if mode != "off":
        generator = build_context_prefix_generator(
            settings if contextual_mode is None else settings.model_copy(update={"rag_contextual_prefix_mode": mode})
        )
        chunks = apply_contextual_prefixes(
            chunks,
            documents,
            generator=generator,
            cached_prefixes=cached_prefixes,
        )
    return chunks


def ensure_chunk_identity(chunks: list[dict]) -> list[dict]:
    """Fill in the identity fields a chunk needs to be cited and invalidated."""
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
