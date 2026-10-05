"""L1 — text normalization and clause segmentation.

Both steps return character spans into the *original* text so a later policy
stage can rewrite one span and keep the rest of the answer.

No domain vocabulary lives here. Chinese has no word boundaries, so matching is
done on normalized characters with explicit offsets rather than on tokens; word
segmentation is deliberately not used, because it cannot help find a known term
and can only change the text before the match.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from backend.safety.models import Clause


# Sentence-level boundaries. Commas are intentionally excluded: a Chinese comma
# frequently does not end a negation's scope, so treating it as a hard boundary
# would cut the look-back window short and reintroduce false positives.
_SENTENCE_BOUNDARY = re.compile(r"[。！？；!?;]")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Normalized:
    text: str
    # normalized index -> original index, so spans map back to the raw input
    source_index: tuple[int, ...]


def _fold(char: str) -> str:
    """Fullwidth -> halfwidth, NFKC-compatible single-character folding."""
    code = ord(char)
    if code == 0x3000:
        return " "
    if 0xFF01 <= code <= 0xFF5E:
        return chr(code - 0xFEE0)
    return char


def normalize(text: str) -> Normalized:
    """Casefold, NFKC-fold and collapse whitespace while keeping an offset map."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    normalized_chars: list[str] = []
    source_index: list[int] = []
    pending_space = False

    for index, char in enumerate(unicodedata.normalize("NFKC", text)):
        folded = _fold(char)
        if _WHITESPACE.fullmatch(folded):
            pending_space = True
            continue
        if pending_space and normalized_chars:
            normalized_chars.append(" ")
            source_index.append(index)
        pending_space = False
        normalized_chars.append(folded.lower())
        source_index.append(index)

    return Normalized("".join(normalized_chars), tuple(source_index))


def to_source_span(normalized: Normalized, span: tuple[int, int]) -> tuple[int, int]:
    """Map a normalized span back to original-text offsets."""
    start, end = span
    if start >= end or not normalized.source_index:
        return (0, 0)
    start = max(0, min(start, len(normalized.source_index) - 1))
    end = max(start + 1, min(end, len(normalized.source_index)))
    return (normalized.source_index[start], normalized.source_index[end - 1] + 1)


def split_clauses(normalized: Normalized) -> tuple[Clause, ...]:
    """Split on sentence boundaries, keeping each clause's span."""
    text = normalized.text
    clauses: list[Clause] = []
    start = 0
    for match in _SENTENCE_BOUNDARY.finditer(text):
        end = match.end()
        if text[start:end].strip():
            clauses.append(Clause(text[start:end], (start, end)))
        start = end
    if text[start:].strip():
        clauses.append(Clause(text[start:], (start, len(text))))
    if not clauses and text:
        clauses.append(Clause(text, (0, len(text))))
    return tuple(clauses)


def clause_of(clauses: tuple[Clause, ...], span: tuple[int, int]) -> int:
    """Index of the clause containing a span, or the last clause as a fallback."""
    for index, clause in enumerate(clauses):
        if clause.span[0] <= span[0] < clause.span[1]:
            return index
    return max(0, len(clauses) - 1)


def left_window(normalized: Normalized, clause: Clause, span: tuple[int, int]) -> str:
    """Text between the clause start and the match — the look-back window."""
    return normalized.text[clause.span[0]:span[0]]
