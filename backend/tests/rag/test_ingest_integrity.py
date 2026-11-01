"""R1: chunking must not lose text, and chunk identity must be stable.

The defect this fixes is specific and was reproduced in R0: ``flush()`` used
``text[:max_chars]``, so any block longer than the cap lost its tail outright rather
than continuing in the next chunk. The first test below is the one that would have
caught it.

The second theme is identity. A chunk id must stay the same when the text at that
position is edited (so an edit is detectable by hash), and two documents that happen to
share a heading must not collide.
"""
from __future__ import annotations

import pytest

from backend.rag.contracts import CHUNKING_VERSION, chunk_id, content_hash
from backend.rag.ingest import chunk_markdown


def _reassemble(chunks: list[dict]) -> str:
    return "\n".join(chunk["text"] for chunk in chunks)


def _non_whitespace(text: str) -> str:
    return "".join(text.split())


# --------------------------------------------------------------------------
# completeness: no text may be dropped
# --------------------------------------------------------------------------

def test_a_line_longer_than_the_cap_is_split_not_truncated():
    """GAP 1 fix: a 2000-character line must survive reassembly in full."""
    long_line = "A" * 2000
    chunks = chunk_markdown({"source": "long.md", "text": "# Heading\n" + long_line})

    assert len(_reassemble(chunks)) >= 2000
    assert _reassemble(chunks).count("A") == 2000


def test_a_long_chinese_line_keeps_its_tail():
    """The R0 corpus puts its answer at the end of a 1070-character line."""
    body = "训练建议应当循序渐进。" * 60 + "遇到平台期先检查睡眠和总热量。"
    chunks = chunk_markdown({"source": "zh.md", "text": "# 长段落\n\n" + body})

    assert _non_whitespace(body)[-20:] in _non_whitespace(_reassemble(chunks))


def test_every_non_whitespace_character_survives():
    """The strong form: reassembly contains every visible character of the source."""
    body = "\n".join([
        "# First",
        "alpha " * 200,
        "# Second",
        "beta " * 200,
    ])
    chunks = chunk_markdown({"source": "big.md", "text": body})
    source_body = "".join(line for line in body.splitlines() if not line.startswith("#"))

    assert _non_whitespace(source_body) == _non_whitespace(_reassemble(chunks))


def test_no_chunk_exceeds_the_configured_cap():
    chunks = chunk_markdown({"source": "big.md", "text": "# H\n" + "x" * 5000},
                            max_chars=400)

    assert all(len(chunk["text"]) <= 400 for chunk in chunks)
    assert len(chunks) >= 12


def test_several_long_lines_each_continue_rather_than_truncate():
    lines = "\n".join("y" * 700 for _ in range(4))
    chunks = chunk_markdown({"source": "many.md", "text": "# H\n" + lines})

    assert _reassemble(chunks).count("y") == 2800


# --------------------------------------------------------------------------
# structure: headings and order are preserved
# --------------------------------------------------------------------------

def test_each_chunk_records_the_heading_it_belongs_to():
    body = "# Alpha\nalpha body\n# Beta\nbeta body\n"
    chunks = chunk_markdown({"source": "h.md", "text": body})

    headings = [chunk["heading"] for chunk in chunks]
    assert headings == ["Alpha", "Beta"]


def test_a_long_section_keeps_its_heading_across_continuations():
    """A continuation chunk still belongs to the section it started in."""
    chunks = chunk_markdown({"source": "h.md", "text": "# Alpha\n" + "z" * 1500},
                            max_chars=400)

    assert all(chunk["heading"] == "Alpha" for chunk in chunks)
    assert len(chunks) >= 4


def test_chunk_order_follows_document_order():
    body = "# One\nfirst\n# Two\nsecond\n# Three\nthird\n"
    chunks = chunk_markdown({"source": "o.md", "text": body})

    assert [chunk["heading"] for chunk in chunks] == ["One", "Two", "Three"]
    assert [chunk["ordinal"] for chunk in chunks] == [0, 1, 2]


def test_ordinals_are_contiguous_from_zero():
    chunks = chunk_markdown({"source": "o.md", "text": "# H\n" + "q" * 2000},
                            max_chars=300)

    assert [chunk["ordinal"] for chunk in chunks] == list(range(len(chunks)))


def test_content_before_the_first_heading_gets_an_overview_heading():
    chunks = chunk_markdown({"source": "p.md", "text": "preamble text\n# Later\nbody\n"})

    assert chunks[0]["heading"] == "Overview"


# --------------------------------------------------------------------------
# identity: stable ids, content hashes, document version
# --------------------------------------------------------------------------

def test_repeated_chunking_produces_identical_ids():
    document = {"source": "s.md", "text": "# H\n" + "w" * 800}

    first = chunk_markdown(document)
    second = chunk_markdown(document)

    assert [c["chunk_id"] for c in first] == [c["chunk_id"] for c in second]


def test_ids_stay_stable_when_the_text_at_that_position_changes():
    """Position identifies the chunk; the hash identifies the version at it."""
    before = chunk_markdown({"source": "s.md", "text": "# H\nalpha"})
    after = chunk_markdown({"source": "s.md", "text": "# H\nbeta"})

    assert before[0]["chunk_id"] == after[0]["chunk_id"]
    assert before[0]["content_hash"] != after[0]["content_hash"]


def test_two_sources_with_the_same_heading_do_not_collide():
    first = chunk_markdown({"source": "a.md", "text": "# Notes\nsame words"})
    second = chunk_markdown({"source": "b.md", "text": "# Notes\nsame words"})

    assert first[0]["chunk_id"] != second[0]["chunk_id"]
    assert first[0]["content_hash"] == second[0]["content_hash"]


def test_each_chunk_carries_a_hash_of_its_own_text():
    chunks = chunk_markdown({"source": "s.md", "text": "# H\nalpha\n# I\nbeta"})

    for chunk in chunks:
        assert chunk["content_hash"] == content_hash(chunk["text"])


def test_the_document_version_changes_only_with_the_document():
    a = chunk_markdown({"source": "s.md", "text": "# H\nalpha"})
    b = chunk_markdown({"source": "s.md", "text": "# H\nalpha"})
    c = chunk_markdown({"source": "s.md", "text": "# H\nalpha edited"})

    assert a[0]["document_version"] == b[0]["document_version"]
    assert a[0]["document_version"] != c[0]["document_version"]


def test_chunks_carry_the_current_chunking_version():
    chunks = chunk_markdown({"source": "s.md", "text": "# H\ntext"})

    assert chunks[0]["chunking_version"] == CHUNKING_VERSION


def test_chunk_ids_match_the_contract_format():
    import re

    chunks = chunk_markdown({"source": "s.md", "text": "# H\ntext"})

    assert re.fullmatch(r"chunk-[a-f0-9]{16,64}", chunks[0]["chunk_id"])


def test_chunk_id_derives_from_source_heading_and_ordinal():
    chunk = chunk_markdown({"source": "s.md", "text": "# H\ntext"})[0]

    assert chunk["chunk_id"] == chunk_id("s.md", "H", 0)


# --------------------------------------------------------------------------
# provenance metadata must not invent authority
# --------------------------------------------------------------------------

def test_absent_provenance_fields_stay_unknown():
    """A document with no declared URL or date must not be given one."""
    chunks = chunk_markdown({"source": "s.md", "text": "# H\ntext"})

    assert chunks[0]["source_url"] is None
    assert chunks[0]["published_at"] is None
    assert chunks[0]["reviewed_at"] is None


def test_declared_provenance_is_carried_through():
    chunks = chunk_markdown({
        "source": "s.md",
        "text": "# H\ntext",
        "source_url": "https://example.invalid/doc",
        "published_at": "2026-01-01",
        "reviewed_at": "2026-02-01",
    })

    assert chunks[0]["source_url"] == "https://example.invalid/doc"
    assert chunks[0]["published_at"] == "2026-01-01"


# --------------------------------------------------------------------------
# the long single-line corpus document is now fully covered
# --------------------------------------------------------------------------

def test_the_fixture_long_line_document_is_fully_recoverable():
    import json
    from pathlib import Path

    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "rag"
    corpus = json.loads((fixtures / "corpus.json").read_text(encoding="utf-8"))
    document = next(d for d in corpus["documents"] if d["source"] == "long-line.md")

    chunks = chunk_markdown(document)
    body = document["text"].splitlines()
    body = [line for line in body if not line.startswith("#")]
    source_body = "".join(body)

    assert _non_whitespace(source_body) == _non_whitespace(_reassemble(chunks))
    # The answer the query case asks for sits at the very end.
    assert "这是本段的结论句" in _reassemble(chunks)
