"""Document parsers for Markdown frontmatter, Markdown tables, and PDFs."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
_TABLE_SEP_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*(?::?-{3,}:?\s*)?\|?\s*$")


def _clean_opt_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Extract optional YAML frontmatter metadata without fabricating absent fields."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw_yaml = match.group(1)
    body = text[match.end() :]
    try:
        parsed = yaml.safe_load(raw_yaml) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(parsed, dict):
        return {}, text

    domain = _clean_opt_str(parsed.get("domain") or parsed.get("scope"))
    meta: dict[str, Any] = {
        "domain": domain,
        "valid_from": _clean_opt_str(parsed.get("valid_from")),
        "expires_at": _clean_opt_str(parsed.get("expires_at")),
        "policy_version": _clean_opt_str(parsed.get("policy_version")),
        "source_url": _clean_opt_str(parsed.get("source_url")),
        "published_at": _clean_opt_str(parsed.get("published_at")),
        "reviewed_at": _clean_opt_str(parsed.get("reviewed_at")),
        "doc_type": _clean_opt_str(parsed.get("doc_type")),
    }
    return {k: v for k, v in meta.items() if v is not None}, body


def infer_domain_from_source(source: str, declared_domain: str | None = None) -> str:
    if declared_domain in {"training", "nutrition", "general"}:
        return declared_domain
    lower = source.lower()
    if any(token in lower for token in ("nutrition", "meal", "diet", "macro", "food")):
        return "nutrition"
    if any(token in lower for token in ("fitness", "exercise", "training", "workout")):
        return "training"
    return "general"


def is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.count("|") >= 2


def is_table_separator(line: str) -> bool:
    return bool(_TABLE_SEP_RE.match(line))


def split_markdown_blocks(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Partition section lines into contiguous prose vs Markdown pipe-table blocks."""
    blocks: list[tuple[str, list[str]]] = []
    prose_buf: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        if i + 1 < n and is_table_row(lines[i]) and is_table_separator(lines[i + 1]):
            if prose_buf:
                blocks.append(("prose", prose_buf))
                prose_buf = []
            table_lines = [lines[i], lines[i + 1]]
            i += 2
            while i < n and is_table_row(lines[i]):
                table_lines.append(lines[i])
                i += 1
            blocks.append(("table", table_lines))
            continue
        prose_buf.append(lines[i])
        i += 1
    if prose_buf:
        blocks.append(("prose", prose_buf))
    return blocks


def parse_pdf_document(path: str | Path) -> dict[str, Any]:
    """Extract structured Markdown-headed sections from a PDF via ``pypdf``."""
    from pypdf import PdfReader

    target = Path(path)
    reader = PdfReader(str(target))
    sections: list[str] = []
    for page_index, page in enumerate(reader.pages, start=1):
        extracted = (page.extract_text() or "").strip()
        if not extracted:
            continue
        sections.append(f"## Page {page_index}\n{extracted}")
    return {
        "source": target.name,
        "text": "\n\n".join(sections),
        "doc_type": "pdf",
        "domain": infer_domain_from_source(target.name),
    }


def load_document_from_path(path: str | Path) -> dict[str, Any]:
    """Load a ``.md`` or ``.pdf`` knowledge document into normalized dict shape."""
    target = Path(path)
    if target.suffix.lower() == ".pdf":
        return parse_pdf_document(target)
    raw = target.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(raw)
    return {
        "source": target.name,
        "text": body,
        **meta,
        "domain": infer_domain_from_source(target.name, meta.get("domain")),
    }
