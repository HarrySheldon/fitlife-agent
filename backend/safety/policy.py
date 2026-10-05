"""L5 — the decision layer.

Maps (concern, modifier, severity) to an action by evaluating the pack's declared
rules in order. It performs no detection: it cannot find a term, and it cannot
change what detection reported. That separation is what lets the policy be edited
without touching detection, and the notices without touching either.
"""
from __future__ import annotations

from backend.safety.models import ACTIONS, Policy, PolicyRule


def _matches(rule: PolicyRule, *, concern: str | None, modifier: str, severity: int) -> bool:
    when = rule.when
    if "concern" in when and when["concern"] != concern:
        return False
    if "modifier" in when and when["modifier"] != modifier:
        return False
    if "severity_at_least" in when and severity < when["severity_at_least"]:
        return False
    if "severity_at_most" in when and severity > when["severity_at_most"]:
        return False
    # An empty condition would match everything, which is a policy authoring bug.
    return bool(when)


def evaluate(
    policy: Policy,
    *,
    concern: str | None,
    modifier: str,
    severity: int,
) -> tuple[str, str | None]:
    """Return the first matching (action, notice) or the pack default."""
    if concern is None:
        return "allow", None
    for rule in policy.rules:
        if _matches(rule, concern=concern, modifier=modifier, severity=severity):
            if rule.action not in ACTIONS:
                raise ValueError(f"Unknown action in policy: {rule.action}")
            return rule.action, rule.notice
    return policy.default_action, None


def validate_policy(policy: Policy) -> None:
    """Reject a policy that could not be evaluated as written."""
    if policy.default_action not in ACTIONS:
        raise ValueError(f"Unknown default action: {policy.default_action}")
    for rule in policy.rules:
        if rule.action not in ACTIONS:
            raise ValueError(f"Unknown action in policy: {rule.action}")
        if not rule.when:
            raise ValueError("A policy rule must declare at least one condition")
        unknown = set(rule.when) - {"concern", "modifier", "severity_at_least", "severity_at_most"}
        if unknown:
            raise ValueError(f"Unknown policy condition: {sorted(unknown)}")
