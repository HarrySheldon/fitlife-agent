"""The safety gate: detection, decision and presentation, wired together.

Consumers call :func:`check_input` and :func:`review_output` and nothing else, so
the three concerns behind them can be changed independently.

Flow::

    normalize -> split_clauses -> find_hits        (detection)
      -> resolve_modifier -> severity              (context)
      -> evaluate                                   (decision)
      -> render                                     (presentation)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from backend.domain.errors import ApplicationError
from backend.safety import pack as pack_loader
from backend.safety.match import build_index, find_hits
from backend.safety.models import Messages, Modifier, Policy, RulePack, SafetyDecision, Verdict
from backend.safety.normalize import normalize, split_clauses, to_source_span
from backend.safety.policy import evaluate
from backend.safety.scope import resolve_modifier, severity_for


SAFETY_RULE_VERSION = "fitlife-safety-v1"
MAX_QUESTION_CHARS = 8_000
_OVERSIZE = 7  # above every pack severity: an oversized input is never shippable

# Safety metadata may only be drawn from the controlled vocabulary. Free text here
# would turn a diagnostic channel into a content leak.
_CONTROLLED_DISCLAIMERS = frozenset({
    "General lifestyle guidance only.",
    "仅供一般生活方式参考。",
})
_CONTROLLED_RISKS = frozenset({
    "low", "emergency", "self_harm", "medical", "extreme_diet",
    "dangerous_training", "input_limit", "review_unavailable", "out_of_scope",
})


def _is_controlled(value: object) -> bool:
    return isinstance(value, str) and (
        value in _CONTROLLED_RISKS or value in _CONTROLLED_DISCLAIMERS
    )


@lru_cache(maxsize=1)
def default_pack() -> RulePack:
    """The pack committed with the application. Loaded once; raises if broken."""
    return pack_loader.load_pack()


class SafetyRefusal(ApplicationError):
    def __init__(self, verdict: Verdict, question: str = "", *, notice: str | None = None) -> None:
        self.verdict = verdict
        super().__init__(
            code="SAFETY_REFUSAL",
            message=notice or "This content needs qualified professional review.",
            status_code=422,
            processing_mode="agent",
            action="Seek qualified help for medical or urgent concerns.",
            retryable=False,
        )

    @property
    def decision(self):
        """Service-level view, resolved lazily to avoid an import cycle."""
        from backend.agent.safety import decision_for

        return decision_for(self.verdict)


@dataclass(frozen=True)
class ReviewResult:
    text: str
    verdict: Verdict
    notice: str | None = None


@dataclass(frozen=True)
class _Signal:
    """What detection found, before any policy decision."""

    concern: str | None = None
    modifier: Modifier = Modifier.asserted
    severity: int = 0
    spans: tuple[tuple[int, int], ...] = field(default=())


def _analyse(text: str, pack: RulePack) -> _Signal:
    """Detect concerns in ``text`` and classify each match's context.

    Two facts are reported separately, because conflating them is what makes a
    gate unable to distinguish "nothing here" from "here, but safely used":

    - ``concern``: the most severe concern found, retained even when its context
      makes it harmless, so a caller can see *what* was noticed;
    - ``severity``: the highest actionable severity across all matches, which is
      0 whenever every match was safe in context.

    Ties keep the first-seen concern so the pack's own order decides, rather than
    an implementation detail.
    """
    if not isinstance(text, str) or len(text) > MAX_QUESTION_CHARS:
        return _Signal(severity=_OVERSIZE)

    normalized = normalize(text)
    clauses = split_clauses(normalized)
    hits = find_hits(normalized, build_index(pack.concerns))

    concern: str | None = None
    best_rank = -1
    modifier = Modifier.asserted
    actionable = 0
    actionable_modifier = Modifier.asserted
    spans: list[tuple[int, int]] = []

    for hit in hits:
        clause = clauses[hit.clause_index]
        hit_modifier = resolve_modifier(normalized, clause, hit, pack.cues)
        hit_severity = severity_for(hit, clause, hit_modifier, pack.cues)
        span = to_source_span(normalized, hit.span)

        # `rank` orders reporting only; it is not an action.
        rank = hit.default_severity
        if rank > best_rank:
            best_rank = rank
            concern = hit.concern
            modifier = hit_modifier
            spans = [span]
        elif rank == best_rank and hit.concern == concern:
            spans.append(span)

        if hit_severity > actionable:
            actionable = hit_severity
            actionable_modifier = hit_modifier

    return _Signal(concern, modifier if concern else Modifier.asserted,
                   max(actionable, 0), tuple(spans))


def _decide(signal: _Signal, policy: Policy) -> tuple[Verdict, str | None]:
    action, notice_key = evaluate(
        policy,
        concern=signal.concern,
        modifier=signal.modifier.value,
        severity=signal.severity,
    )
    if signal.severity > 6:
        action, notice_key = "refuse", "generic"
    verdict = Verdict(
        detected=signal.concern is not None or signal.severity > 6,
        filtered=action != "allow",
        action=action,
        severity=min(signal.severity, _OVERSIZE),
        concern=signal.concern,
        modifiers=(signal.modifier,) if signal.concern else (),
        evidence_spans=signal.spans,
    )
    return verdict, notice_key


def _notice(notice_key: str | None, messages: Messages) -> str | None:
    return messages.notice(notice_key)


def _primary(*signals: _Signal) -> _Signal:
    """Pick the signal that carries the most information.

    Severity alone is not enough: a safe-in-context match reports severity 0 but
    still names a concern, and dropping it would hide *what* was noticed. So a
    signal that names a concern outranks one that does not, and severity only
    breaks ties among comparable signals.
    """
    return max(signals, key=lambda signal: (signal.concern is not None, signal.severity))


def check_input(question: str, *, pack: RulePack | None = None) -> Verdict:
    """Input gate. Raises :class:`SafetyRefusal` when the question must not proceed."""
    active = pack or default_pack()
    verdict, notice_key = _decide(_analyse(question, active), active.policy)
    if verdict.action in {"refuse", "escalate"}:
        raise SafetyRefusal(verdict, question, notice=_notice(notice_key, active.messages))
    return verdict


def review_output(
    question: str,
    draft: str,
    *,
    reviewer=None,
    pack: RulePack | None = None,
    policy: Policy | None = None,
    messages: Messages | None = None,
) -> ReviewResult:
    """Output gate. Returns the text to ship plus the verdict that produced it.

    ``policy`` and ``messages`` are injected separately so that changing one
    cannot silently change the other.
    """
    active = pack or default_pack()
    active_policy = policy or active.policy
    active_messages = messages or active.messages

    question_signal = _analyse(question, active)
    input_verdict, input_notice_key = _decide(question_signal, active_policy)
    # A high-risk input is refused before any draft is considered.
    if input_verdict.action in {"refuse", "escalate"}:
        raise SafetyRefusal(input_verdict, question,
                            notice=_notice(input_notice_key, active_messages))

    signal = _primary(question_signal, _analyse(draft, active))
    verdict, notice_key = _decide(signal, active_policy)

    # An extra reviewer may only tighten. It is consulted after the deterministic
    # decision and re-validated at this boundary: a bare mapping is rejected (it
    # would be coerced into a plausible-looking decision) and a constructed
    # instance is rebuilt through the constructor so validation cannot be skipped.
    if reviewer is not None:
        try:
            decision = reviewer.review(question, draft)
            if not isinstance(decision, SafetyDecision):
                raise ValueError("A reviewer must return a SafetyDecision")
            decision = SafetyDecision(
                outcome=decision.outcome,
                risk_category=decision.risk_category,
                violations=decision.violations,
                required_disclaimer=decision.required_disclaimer,
            )
            if decision.outcome == "allow" and decision.risk_category != "low":
                raise ValueError("Inconsistent safety decision")
            # Safety metadata is a controlled vocabulary. A reviewer that puts free
            # text into it is leaking content through a diagnostic channel.
            if any(not _is_controlled(value) for value in decision.violations):
                raise ValueError("Safety metadata must use controlled categories")
            if decision.required_disclaimer is not None and not _is_controlled(
                decision.required_disclaimer
            ):
                raise ValueError("A disclaimer must be a controlled notice")
        except Exception:
            # Review did not run, so nothing was filtered by it. The draft is still
            # withheld: fail closed.
            unavailable = Verdict(True, False, "refuse", verdict.severity,
                                  "review_unavailable", verdict.modifiers,
                                  verdict.evidence_spans)
            raise SafetyRefusal(unavailable, question,
                                notice=active_messages.notice("*")) from None
        if decision.outcome == "refuse":
            raised = Verdict(True, True, "refuse", max(verdict.severity, 3),
                             verdict.concern, verdict.modifiers, verdict.evidence_spans)
            raise SafetyRefusal(raised, question, notice=active_messages.notice("*"))

    if verdict.action == "allow":
        return ReviewResult(text=draft, verdict=verdict)

    notice = _notice(notice_key, active_messages)
    if verdict.action == "disclose":
        # Disclose keeps the answer and adds the boundary statement.
        return ReviewResult(
            text=f"{draft}\n\n{notice}" if notice else draft, verdict=verdict, notice=notice
        )
    raise SafetyRefusal(verdict, question, notice=notice)
