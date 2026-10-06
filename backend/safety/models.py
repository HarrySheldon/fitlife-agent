"""Data model for the safety rule packs.

Every type here is pack-facing data. The engine reads these; it never embeds a
term, a notice or a policy threshold.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict

MIN_SEVERITY = 0
MAX_SEVERITY = 6

Action = Literal["allow", "annotate", "disclose", "mask", "refuse", "escalate", "rewrite"]
ACTIONS: frozenset[str] = frozenset(
    {"allow", "annotate", "disclose", "mask", "refuse", "escalate", "rewrite"}
)

# Actions that ship the draft (possibly modified) rather than withholding it.
SHIPPING_ACTIONS: frozenset[str] = frozenset({"allow", "annotate", "disclose", "mask"})

# `mask` rewrites matched spans, so it is only meaningful where there is a draft to
# rewrite. A policy that asks for it on the input side is a configuration error.
OUTPUT_ONLY_ACTIONS: frozenset[str] = frozenset({"mask"})

# Cue classes are part of the algorithm: the engine defines what each class means,
# a pack only supplies its phrases. Two members carry hardcoded precedence —
# `pseudo` cancels `negation`, and `termination` cuts the look-back window.
CUE_CLASSES: tuple[str, ...] = (
    "negation",
    "speculation",
    "referral",
    "deontic",
    "termination",
    "pseudo",
)

# Domains group concerns. They are the analysis domains of the product, not an
# invented metaphor; a new analysis domain adds a group rather than an engine edit.
KNOWN_DOMAINS: frozenset[str] = frozenset({"nutrition", "training", "shared"})


class Modifier(str, Enum):
    """How a matched term is being used in its clause."""

    asserted = "asserted"
    negated = "negated"
    prescriptive = "prescriptive"
    hypothetical = "hypothetical"
    conditional_referral = "conditional_referral"
    third_party = "third_party"
    definitional = "definitional"
    pseudo = "pseudo"


RiskCategory = Literal[
    "low",
    "emergency",
    "self_harm",
    "medical",
    "extreme_diet",
    "dangerous_training",
    "input_limit",
    "review_unavailable",
    "out_of_scope",
    # Demeaning or insulting the user. Judged by the model reviewer rather than by
    # rules: the clearest cases are compliments used as insults, which no word list
    # holds.
    "harassment",
]
ControlledDisclaimer = Literal[
    "General lifestyle guidance only.", "仅供一般生活方式参考。"
]


class SafetyDecision(BaseModel):
    """Service-level view of a verdict.

    Strict, frozen and revalidated at the extension boundary: a reviewer that
    constructs one without validation must not be able to inject free text or an
    inconsistent outcome/category pair.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    outcome: Literal["allow", "rewrite", "refuse"]
    risk_category: RiskCategory = "low"
    violations: tuple[RiskCategory, ...] = ()
    required_disclaimer: ControlledDisclaimer | None = None
    # Additive: everything below is reported, never required.
    detected: bool = False
    filtered: bool = False
    severity: int = 0
    modifiers: tuple[str, ...] = ()
    evidence_spans: tuple[tuple[int, int], ...] = ()

    @classmethod
    def allow(cls) -> "SafetyDecision":
        return cls(outcome="allow", risk_category="low")


@dataclass(frozen=True)
class Concern:
    id: str
    domain: str
    surface: tuple[str, ...]
    default_severity: int
    title: str = ""


@dataclass(frozen=True)
class CueTables:
    negation: tuple[str, ...] = ()
    speculation: tuple[str, ...] = ()
    referral: tuple[str, ...] = ()
    deontic: tuple[str, ...] = ()
    termination: tuple[str, ...] = ()
    pseudo: tuple[str, ...] = ()
    third_party: tuple[str, ...] = ()
    definitional_markers: tuple[str, ...] = ()
    imperative_markers: tuple[str, ...] = ()
    # Manipulation patterns keyed by pattern id. A separate axis from cue classes:
    # these describe *how* a request is framed, not what it is about.
    jailbreak_patterns: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # Units that mark a number as a claim about a measurement.
    measurement_units: tuple[str, ...] = ()

    def class_of(self, name: str) -> tuple[str, ...]:
        return tuple(getattr(self, name))


@dataclass(frozen=True)
class PolicyRule:
    when: dict
    action: str
    notice: str | None = None


@dataclass(frozen=True)
class Policy:
    default_action: str = "allow"
    rules: tuple[PolicyRule, ...] = ()


@dataclass(frozen=True)
class Messages:
    locale: str
    notices: dict

    def notice(self, key: str | None) -> str | None:
        if key is None:
            return None
        return self.notices.get(key) or self.notices.get("*")


@dataclass(frozen=True)
class RulePack:
    schema_version: int
    pack_version: str
    locale: str
    concerns: tuple[Concern, ...]
    cues: CueTables
    policy: Policy
    messages: Messages

    def concern(self, concern_id: str) -> Concern:
        for concern in self.concerns:
            if concern.id == concern_id:
                return concern
        raise KeyError(concern_id)


@dataclass(frozen=True)
class Clause:
    text: str
    span: tuple[int, int]


@dataclass(frozen=True)
class TermHit:
    concern: str
    span: tuple[int, int]
    clause_index: int
    default_severity: int


VerdictSource = Literal[
    "gate",              # decided by the deterministic rule pack
    "review",            # an extension reviewer rejected the draft
    "review_unavailable",  # the reviewer could not run, so the draft was withheld
]


@dataclass(frozen=True)
class Verdict:
    """Separates what was noticed from what is done about it."""

    detected: bool
    filtered: bool
    action: str
    severity: int
    concern: str | None
    modifiers: tuple[Modifier, ...]
    evidence_spans: tuple[tuple[int, int], ...]
    # Audit trail: auditing asks which rule fired and which patterns matched, not
    # only what the outcome was.
    rule_version: str = ""
    matched_patterns: tuple[str, ...] = field(default=())
    source: VerdictSource = "gate"
    # A category reported by an extension reviewer. Kept separate from `concern`,
    # which is rule-pack vocabulary: a reviewer is not describing a rule that fired,
    # and conflating the two would put non-pack values where the policy looks for
    # concerns.
    review_category: RiskCategory | None = None

    @property
    def blocked(self) -> bool:
        return self.action in {"refuse", "escalate"}

    @property
    def rewritten(self) -> bool:
        return self.action in {"mask", "refuse", "escalate"}
