"""Evidence: a bounded snapshot of what a retrieval actually returned, and its checks.

The point of this layer is that an answer's citations become *falsifiable*. A citation is
accepted only when the id exists in this snapshot, the snapshot belongs to the release the
answer was built on, and the content hash still describes the cited text. Anything else is
reported rather than smoothed over.

A second, different failure is handled here too: claiming authority ("the materials
show...") when nothing was retrieved. That is not a bad citation, it is an unsupported
claim, and it gets its own verdict so the two are not confused in a report.

Finally, source text is data. A document that says "ignore all previous instructions" is
documenting an attack, not issuing one, so instruction-shaped text is neutralised before
it can sit in a position where it reads as a directive.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.rag.contracts import RetrievalResult, RetrievalStatus, content_hash

DEFAULT_MAX_BLOCKS = 5
NEUTRALISED = "（此来源片段包含无法作为指令的内容，已省略）"

# Instruction-shaped phrases. Deliberately narrow: this is a defence against corpus text
# being read as a directive, not a general content filter.
_INSTRUCTION_PATTERNS = (
    r"ignore\s+(?:all\s+)?(?:the\s+)?previous\s+instructions?",
    r"ignore\s+.{0,20}(?:prior|above)\s+instructions?",
    r"system\s+prompt",
    r"you\s+(?:may|can|should)\s+now\s+(?:call|use|read)\s+any",
    r"忽略.{0,12}(?:之前|以上|前面)?.{0,6}指令",
    r"授予.{0,20}权限",
    r"系统提示",
)
_INSTRUCTION_RE = re.compile("|".join(_INSTRUCTION_PATTERNS), re.I)

# Authority-claim phrases: an answer asserting that a source supports it.
_AUTHORITY_RE = re.compile(
    r"根据(?:资料|材料|来源|文档|文献)|资料(?:显示|表明|指出)|研究(?:显示|表明|指出)"
    r"|据(?:资料|文献)|according to (?:the )?(?:sources?|materials?|documents?|knowledge base|literature)"
    r"|(?:the )?(?:sources?|materials?|documents?) (?:show|shows|suggest|suggests|indicate|indicates)"
    r"|research (?:shows|suggests|indicates)",
    re.I,
)
# Citation references as they appear in prose: E1, E12.
_CITATION_RE = re.compile(r"\bE(\d{1,3})\b")


def sanitize_evidence_text(text: str) -> str:
    """Replace instruction-shaped content with a neutral marker."""
    if not _INSTRUCTION_RE.search(text):
        return text
    return _INSTRUCTION_RE.sub(NEUTRALISED, text)


@dataclass(frozen=True)
class CitationVerdict:
    valid: bool
    reason: str | None


@dataclass(frozen=True)
class EvidenceBlock:
    evidence_id: str
    chunk_id: str
    content_hash: str
    source: str
    heading: str
    text: str


@dataclass(frozen=True)
class EvidenceSet:
    status: RetrievalStatus
    release_id: str | None
    blocks: tuple[EvidenceBlock, ...]
    reason: str | None = None

    def block(self, evidence_id: str) -> EvidenceBlock | None:
        for item in self.blocks:
            if item.evidence_id == evidence_id:
                return item
        return None

    def check_citation(self, evidence_id: str, *, release_id: str | None = None,
                       content_hash_: str | None = None) -> CitationVerdict:
        block = self.block(evidence_id)
        if block is None:
            return CitationVerdict(False, "unknown_evidence_id")
        if release_id is not None and release_id != self.release_id:
            # A different release is a different corpus; citing across it would quote
            # text this answer never saw.
            return CitationVerdict(False, "release_mismatch")
        if content_hash_ is not None and content_hash_ != block.content_hash:
            return CitationVerdict(False, "hash_mismatch")
        return CitationVerdict(True, None)

    def as_blocks(self) -> list[dict]:
        """The payload a tool hands to the model: data, with ids it can cite."""
        return [
            {
                "evidence_id": block.evidence_id,
                "chunk_id": block.chunk_id,
                "source": block.source,
                "heading": block.heading,
                "text": block.text,
            }
            for block in self.blocks
        ]


@dataclass(frozen=True)
class AnswerReport:
    valid: bool
    problems: tuple[str, ...]


def build_evidence(result: RetrievalResult, *,
                   max_blocks: int = DEFAULT_MAX_BLOCKS) -> EvidenceSet:
    """Turn a retrieval result into a bounded, citable snapshot."""
    if max_blocks < 1:
        raise ValueError("max_blocks must be positive")
    if result.status != "ok":
        return EvidenceSet(status=result.status, release_id=result.release_id,
                           blocks=(), reason=result.fallback_reason)
    blocks: list[EvidenceBlock] = []
    for position, hit in enumerate(result.hits[:max_blocks], start=1):
        blocks.append(EvidenceBlock(
            evidence_id=f"E{position}",
            chunk_id=hit.chunk_id,
            # The hash describes the text as retrieved, not as sanitised, so a citation
            # remains checkable after neutralisation.
            content_hash=hit.content_hash,
            source=hit.source,
            heading=hit.heading,
            text=sanitize_evidence_text(hit.text),
        ))
    return EvidenceSet(status="ok", release_id=result.release_id, blocks=tuple(blocks),
                       reason=result.fallback_reason)


def check_answer(answer: str, evidence: EvidenceSet) -> AnswerReport:
    """Check an answer's citations and its authority claims against the snapshot."""
    problems: list[str] = []
    for match in _CITATION_RE.finditer(answer):
        evidence_id = f"E{match.group(1)}"
        verdict = evidence.check_citation(evidence_id)
        if not verdict.valid:
            problems.append(f"invalid_citation:{evidence_id}:{verdict.reason}")

    if _AUTHORITY_RE.search(answer) and not evidence.blocks:
        problems.append("unsourced_claim")

    return AnswerReport(valid=not problems, problems=tuple(problems))
