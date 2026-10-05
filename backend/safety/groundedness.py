"""Groundedness: numbers the draft states but the data does not support.

The writer is told to state a number only when a tool result provides it. That is a
request, not a guarantee, and the failure is quiet: a fabricated intake figure looks
exactly like a measured one. This module checks the claim against the data.

The engine stays domain-free. Which numbers are checkable, and what a number has to
be near to count as supported, are supplied by the caller and by the rule pack - the
same way policy and notices are injected. Nothing here knows what a calorie is.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# A number, optionally swept up in thousands separators, followed by a unit or a
# percent sign. The unit is captured but never interpreted: it is only a hint that
# the number is a claim about a measurement rather than a heading or a list index.
_NUMBER = r"[-+]?\d[\d,]*(?:\.\d+)?"


def _compile(units: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(unit) for unit in sorted(units, key=len, reverse=True))
    if not alternatives:
        return re.compile(rf"(?P<number>{_NUMBER})(?:\s*%)?")
    return re.compile(rf"(?P<number>{_NUMBER})\s*(?P<unit>{alternatives}|%)")


@dataclass(frozen=True)
class NumberClaim:
    """A number the draft presents as a measurement."""

    value: float
    text: str
    unit: str | None
    span: tuple[int, int]


@dataclass(frozen=True)
class GroundednessReport:
    claims: tuple[NumberClaim, ...] = field(default=())
    unsupported: tuple[NumberClaim, ...] = field(default=())
    # What the check was measured against, echoed so a decision is reviewable.
    allowed: tuple[float, ...] = field(default=())

    @property
    def grounded(self) -> bool:
        return not self.unsupported


def claim_numbers(text: str, units: tuple[str, ...] = ()) -> tuple[NumberClaim, ...]:
    """Extract the numbers the text presents as measurements."""
    pattern = _compile(units)
    claims: list[NumberClaim] = []
    for match in pattern.finditer(text):
        raw = match.group("number").replace(",", "")
        try:
            value = float(raw)
        except ValueError:  # pragma: no cover - the pattern only matches numbers
            continue
        unit = match.groupdict().get("unit")
        claims.append(
            NumberClaim(value=value, text=match.group(0), unit=unit, span=match.span())
        )
    return tuple(claims)


def supporting_values(tool_results) -> tuple[float, ...]:
    """Every number the tool results contain, plus values they imply.

    Sums, differences and ratios are included because a writer that adds two
    grounded figures, or reports one as a share of another, is still grounded. The
    ratios are the reason a target-met percentage does not read as a fabrication.
    """
    numbers: list[float] = []

    def walk(value) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            numbers.append(float(value))
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(tool_results)
    base = tuple(dict.fromkeys(numbers))

    derived: list[float] = []
    for index, left in enumerate(base):
        for right in base[index + 1:]:
            derived.extend((left + right, left - right, right - left))
    for left in base:
        for right in base:
            if right:
                derived.append(left / right * 100.0)

    return tuple(dict.fromkeys(base + tuple(derived)))


def _close(claim: float, allowed: float, tolerance: float) -> bool:
    if claim == allowed:
        return True
    scale = max(abs(claim), abs(allowed))
    if scale == 0:
        return True
    return abs(claim - allowed) <= max(abs(allowed) * tolerance, 0.51)


def check_groundedness(
    draft: str,
    *,
    allowed: tuple[float, ...],
    units: tuple[str, ...] = (),
    tolerance: float = 0.02,
) -> GroundednessReport:
    """Report the numbers in the draft that the supplied data does not support.

    ``allowed`` empty means the data carried no figures at all, so every measurement
    the draft states is unsupported. That is the case worth catching: a fabricated
    weekly average is indistinguishable from a measured one on the page.
    """
    claims = claim_numbers(draft, units)
    unsupported = tuple(
        claim
        for claim in claims
        if not any(_close(claim.value, value, tolerance) for value in allowed)
    )
    return GroundednessReport(claims=claims, unsupported=unsupported, allowed=allowed)
