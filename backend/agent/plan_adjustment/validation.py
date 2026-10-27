"""Deterministic joint validation for one candidate bundle.

Three rules shape this module.

**One source of thresholds.** The reviewed medical numbers (calorie floor,
protein per kilogram, weekly frequency, consecutive intensity, rest days) stay in
``backend.agent.validator`` and are reused through ``legacy_violations``. A second
copy here would eventually disagree with the first, and the user would be told
two different things about the same plan.

**Authorization before explanation.** The round's reservation names the domains
that may be touched; a bundle that reaches past it is rejected as a scope
problem, not as a value problem, because "your meal text is too long" would leak
that the patch was otherwise acceptable.

**Do not pass what could not be checked.** A plan whose meals or days have a
shape the per-domain checks cannot read is reported as a structure violation.
Silently skipping the check and returning ``passed`` is how an unverified
candidate becomes an activated plan.

Nothing here holds a gateway, a repository or a clock: ``evaluate`` is a pure
function of (base, bundle, constraints, round, previous digests).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from backend.domain.plan_adjustment import (
    EQUIPMENT_TOKENS,
    EXERCISE_EQUIPMENT,
    CandidateBundle,
    CandidateVerdict,
    PlanConstraints,
    PlanPatchError,
    Violation,
    apply_patches,
    bundle_identity,
    legacy_violations,
    preserves_targets,
    validate_bundle,
)

# A patch cannot repair these. Retrying costs a round and tells the model to
# solve a problem that lives outside the plan, so the task stops and asks.
UNFIXABLE_CODES = frozenset({"CONSTRAINT_MISSING", "PLAN_FORMAT_UNSUPPORTED",
                             "SAFETY_CONDITION_BLOCKS_DIET"})

_DOMAIN_ROOTS = {"training": "workout_plan", "diet": "diet_plan"}


def _digest(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def candidate_plan(base: dict, bundle: CandidateBundle, change_domains: frozenset[str]) -> dict | None:
    """The merged plan, or ``None`` when the bundle could not be applied.

    The caller stores exactly what this returns, so the bytes that were validated
    and the bytes that would be activated cannot drift apart.
    """
    try:
        return apply_patches(base, bundle.patches, change_domains)
    except PlanPatchError:
        return None


def domain_digests(plan: dict) -> tuple[tuple[str, str], ...]:
    """One digest per domain, so a later round can prove it left a domain alone."""
    return tuple((domain, _digest(plan.get(root)))
                 for domain, root in sorted(_DOMAIN_ROOTS.items()))


def _token(value: Any) -> str:
    return str(value).strip().lower()


def _round_scope(bundle: CandidateBundle, round_domains: frozenset[str]) -> list[Violation]:
    return [Violation(code="DOMAIN_FROZEN", domain=domain, path="bundle.domains")
            for domain in sorted(bundle.domains() - round_domains)]


def _format_violations(base: dict) -> list[Violation]:
    """Both roots must be mappings before any per-domain check can read them."""
    violations: list[Violation] = []
    for domain, root in sorted(_DOMAIN_ROOTS.items()):
        if not isinstance(base.get(root), dict):
            violations.append(Violation(code="PLAN_FORMAT_UNSUPPORTED", domain=domain, path=root))
    return violations


_MISSING_DOMAIN = {
    "constraints.allergies_or_restrictions": "diet",
    "constraints.action_restrictions": "training",
    "constraints.available_equipment": "training",
}


def _equipment_unreadable(constraints: PlanConstraints) -> bool:
    """A vocabulary this validator cannot read is not the same as "no equipment".

    Without this, a profile that stores ``gym`` instead of ``barbell`` would make
    every candidate fail on equipment -- an unfixable verdict that spends the
    repair budget proving it twice.
    """
    tokens = {_token(item) for item in constraints.available_equipment or ()}
    return bool(tokens - EQUIPMENT_TOKENS)


def missing_constraint_paths(constraints: PlanConstraints) -> list[str]:
    """The constraint fields a task must ask about before it can validate.

    Public because the projection needs the same answer without a stored verdict:
    a task stopped for a missing constraint has no candidate to explain itself.
    """
    paths: list[str] = []
    if constraints.allergies_or_restrictions is None:
        paths.append("constraints.allergies_or_restrictions")
    if constraints.action_restrictions is None:
        paths.append("constraints.action_restrictions")
    if constraints.available_equipment is None or _equipment_unreadable(constraints):
        paths.append("constraints.available_equipment")
    return paths


def _missing_constraints(constraints: PlanConstraints) -> list[Violation]:
    """Unknown is not empty: a check that cannot run must ask, not pass."""
    return [Violation(code="CONSTRAINT_MISSING", domain=_MISSING_DOMAIN[path], path=path)
            for path in missing_constraint_paths(constraints)]


def _structure_violations(plan: dict) -> list[Violation]:
    """Shapes the checks depend on. An unreadable list cannot be validated."""
    violations: list[Violation] = []
    diet = plan.get("diet_plan")
    meals = diet.get("meals") if isinstance(diet, dict) else None
    if isinstance(diet, dict) and not isinstance(meals, list):
        violations.append(Violation(code="PLAN_STRUCTURE_MISSING", domain="diet", path="diet_plan.meals"))
    elif isinstance(meals, list) and any(not isinstance(item, (str, dict)) for item in meals):
        violations.append(Violation(code="PLAN_STRUCTURE_MISSING", domain="diet", path="diet_plan.meals"))
    workout = plan.get("workout_plan")
    days = workout.get("days") if isinstance(workout, dict) else None
    if isinstance(workout, dict) and not isinstance(days, list):
        violations.append(Violation(code="PLAN_STRUCTURE_MISSING", domain="training", path="workout_plan.days"))
    elif isinstance(days, list) and any(not isinstance(day, dict) for day in days):
        violations.append(Violation(code="PLAN_STRUCTURE_MISSING", domain="training", path="workout_plan.days"))
    return violations


def _training_constraints(plan: dict, constraints: PlanConstraints) -> list[Violation]:
    """Hard constraints that are not medical thresholds: what the user can do.

    ``session_minutes`` is a comfort bound, so an unknown value skips the duration
    check instead of blocking the task. Equipment is a safety bound, so an
    unknown value is reported by ``_missing_constraints`` and never skipped.
    """
    workout = plan.get("workout_plan") or {}
    days = workout.get("days") if isinstance(workout, dict) else None
    if not isinstance(days, list):
        return []
    forbidden = {_token(item) for item in constraints.forbidden_exercises}
    available = (None if constraints.available_equipment is None
                 else {_token(item) for item in constraints.available_equipment})
    violations: list[Violation] = []
    for index, day in enumerate(days):
        if not isinstance(day, dict):
            continue
        path = f"workout_plan.days.{index}"
        for exercise in day.get("exercises") or ():
            if not isinstance(exercise, dict):
                continue
            name = _token(exercise.get("name"))
            if name and name in forbidden:
                violations.append(Violation(code="FORBIDDEN_EXERCISE", domain="training", path=path))
                break
            needed = EXERCISE_EQUIPMENT.get(name)
            # A bodyweight movement needs nothing, so it is never blocked by a
            # profile that happens not to list "bodyweight" as equipment.
            if available is not None and needed and needed != "bodyweight" and needed not in available:
                violations.append(Violation(code="EQUIPMENT_UNAVAILABLE", domain="training", path=path))
                break
        minutes = day.get("duration_min")
        if (constraints.session_minutes is not None and isinstance(minutes, int)
                and minutes > constraints.session_minutes):
            violations.append(Violation(code="SESSION_TOO_LONG", domain="training", path=path))
    return violations


def _frozen_changes(patched: dict, frozen_digests: Mapping[str, str]) -> list[Violation]:
    """A domain that already passed must still hash to what it hashed to before.

    The round scope stops the bundle from *touching* a frozen domain. This catches
    the other way drift happens: the base plan itself moved underneath the task.
    """
    actual = dict(domain_digests(patched))
    return [Violation(code="FROZEN_DOMAIN_CHANGED", domain=domain,
                      path=_DOMAIN_ROOTS.get(domain, "plan"))
            for domain, expected in sorted(frozen_digests.items())
            if domain in actual and actual[domain] != expected]


def _safety_condition_diet(document: dict, constraints: PlanConstraints,
                           base: dict | None) -> list[Violation]:
    """A declared safety condition makes the diet domain non-adjustable.

    The bundle path refuses this before the patches are applied. Confirmation holds
    a merged document instead of a bundle, so it has to answer the same question a
    different way: did the diet change at all?

    Without a base the answer is not knowable, and an unprovable diet change is
    refused rather than assumed absent -- that is the whole point of the check.
    """
    if not constraints.safety_conditions:
        return []
    if base is None or document.get("diet_plan") != base.get("diet_plan"):
        return [Violation(code="SAFETY_CONDITION_BLOCKS_DIET", domain="diet",
                          path="diet_plan")]
    return []


class PlanValidation:
    """The deterministic evaluator a ``PlanTaskSession`` is given.

    It is stateless on purpose: the same (base, bundle, constraints, round) always
    produces the same verdict, which is what lets the repository treat a
    submission as replayable and the evaluation suite treat it as reproducible.
    """

    def review_document(self, document: dict, constraints: PlanConstraints, *,
                        base: dict | None = None) -> list[Violation]:
        """Re-check a stored candidate as a document rather than as a bundle.

        Confirmation holds the merged plan, not the patches that produced it, so
        the bundle checks cannot be re-run. Every check that reads the plan
        itself can be -- and the reviewed medical thresholds live in that set,
        which is the part that matters. ``base`` enables the target-preservation
        comparison, which is the only check that needs two documents.
        """
        violations = _format_violations(document)
        if violations:
            return violations
        violations += _missing_constraints(constraints)
        violations += _safety_condition_diet(document, constraints, base)
        violations += _structure_violations(document)
        violations += _training_constraints(document, constraints)
        if not violations:
            if base is not None:
                violations += list(preserves_targets(base, document))
            if not violations:
                violations += legacy_violations(document, constraints)
        return violations

    def evaluate(self, base: dict, bundle: CandidateBundle, constraints: PlanConstraints, *,
                 change_domains: frozenset[str],
                 round_domains: frozenset[str] | None = None,
                 frozen_digests: Mapping[str, str] | None = None) -> CandidateVerdict:
        candidate_id, digest, dependency = bundle_identity(base, bundle)
        patched = candidate_plan(base, bundle, change_domains)
        digests = domain_digests(patched if patched is not None else base)

        def verdict(violations: list[Violation]) -> CandidateVerdict:
            failed = tuple(sorted({item.domain for item in violations},
                                  key=lambda domain: (domain != "training", domain)))
            return CandidateVerdict(
                candidate_id=candidate_id, digest=digest, passed=not violations,
                failed_domains=failed, violations=tuple(violations),
                dependency_digest=dependency, domain_digests=digests,
            )

        violations: list[Violation] = []
        if round_domains is not None:
            # Authorization first: a bundle may not reach past the reserved round.
            violations += _round_scope(bundle, round_domains)
        violations += _format_violations(base)
        if violations:
            return verdict(violations)

        # The Task 1 layer: merge, target preservation, reviewed thresholds and
        # missing necessary constraints -- in that order, with authorization first.
        task_verdict = validate_bundle(base, bundle, constraints, change_domains=change_domains)
        if task_verdict.violations:
            return verdict(list(task_verdict.violations))

        violations += _missing_constraints(constraints)
        if not violations:
            if patched is None:
                # Unreachable when the Task 1 layer passed, and still handled: a
                # verdict must never report a pass on a plan that was not built.
                violations.append(Violation(code="PLAN_FORMAT_UNSUPPORTED",
                                            domain="training", path="plan"))
            else:
                violations += _structure_violations(patched)
                violations += _training_constraints(patched, constraints)
                violations += _frozen_changes(patched, frozen_digests or {})
        return verdict(violations)
