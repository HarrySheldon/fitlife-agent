"""Context sanitization: the check that runs where untrusted data enters the model.

The input gate reads the user's question and nothing else. Content that reaches the
model through tool results, the profile, or retrieved documents never passes it, so
a record whose text reads like an instruction would be handed to the model as
context. That is the indirect half of prompt injection, and it needs its own
position rather than another rule inside the input gate.

Scope is deliberately narrow. Only one field in this project's tool results carries
user-written text into the model: `meal_analysis.highest_calorie_food.food`. Rather
than enumerate carriers - which would rot as tools change - every string in the
payload is walked and the ones we authored ourselves are skipped by path. Strings
we did not author are, by construction, the ones that could have come from a user.

What this layer does not do is decide about the request. A user asking "how many
calories did I eat this week" is entitled to an answer even when a record of theirs
contains something odd, so a hit removes that fragment from the context and the
request proceeds. Refusing the whole request would be over-refusal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.safety.models import CueTables, Policy, RulePack
from backend.safety.normalize import normalize
from backend.safety.scope import detect_jailbreak

# Keys whose string values this project authored, so they are not user text. A
# retrieved document is a repository asset; the intent and query are ours; the
# validation result is produced by a deterministic tool.
PROTECTED_KEYS: frozenset[str] = frozenset(
    {
        "intent",
        "detected_intent",
        "retrieved_docs",
        "retrieval_query",
        "validation_result",
        "source",
        "trust",
    }
)

# Profile fields are the user's own answers to a fixed form. They can contain free
# text, but they are never read as instructions in practice, and scanning them would
# flag harmless values such as a stated preference. They are left alone on purpose.
PROTECTED_PREFIXES: tuple[str, ...] = ("profile",)

REDACTION = "（此记录内容无法作为指令处理，已省略）"

_CONTROL_CHARS = re.compile(r"[\u200b-\u200f\u2028-\u202e\ufeff]")


@dataclass(frozen=True)
class ContextFinding:
    """One string in the model context that read like an instruction."""

    path: str
    patterns: tuple[str, ...]
    excerpt: str


@dataclass(frozen=True)
class ContextReport:
    findings: tuple[ContextFinding, ...] = field(default=())
    redacted: bool = False

    @property
    def clean(self) -> bool:
        return not self.findings


def _walk(value: Any, path: str):
    """Yield (path, string) for every user-authored string in the structure."""
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            if str(key) in PROTECTED_KEYS:
                continue
            if path and any(child.startswith(p) for p in PROTECTED_PREFIXES):
                continue
            yield from _walk(item, child)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")
    elif isinstance(value, str) and value.strip():
        yield path, value


def _strip_invisible(text: str) -> str:
    """Drop zero-width and bidi controls.

    These carry no meaning to a reader but are a documented way to hide an
    instruction from a human while the model still parses it.
    """
    return _CONTROL_CHARS.sub("", text)


def scan_context(payload: Any, cues: CueTables) -> tuple[ContextFinding, ...]:
    """Report user-authored strings that read like an instruction."""
    findings: list[ContextFinding] = []
    for path, text in _walk(payload, ""):
        cleaned = _strip_invisible(text)
        patterns = detect_jailbreak(normalize(cleaned), cues)
        if patterns:
            findings.append(
                ContextFinding(path=path, patterns=patterns, excerpt=cleaned[:40])
            )
    return tuple(findings)


def _redact(value: Any, path: str, hits: dict[str, ContextFinding]) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            result[key] = _redact(item, child, hits)
        return result
    if isinstance(value, (list, tuple)):
        return [_redact(item, f"{path}[{index}]", hits) for index, item in enumerate(value)]
    if isinstance(value, str) and path in hits:
        return REDACTION
    return value


def sanitize_context(
    payload: Any, pack: RulePack, *, policy: Policy | None = None
) -> tuple[Any, ContextReport]:
    """Return the payload with instruction-like user text removed.

    `policy` is accepted so a pack can later choose to observe rather than redact,
    matching what `annotate` does for the other positions.
    """
    findings = scan_context(payload, pack.cues)
    if not findings:
        return payload, ContextReport()
    hits = {finding.path: finding for finding in findings}
    cleaned = _redact(payload, "", hits)
    return cleaned, ContextReport(findings=findings, redacted=True)
