"""Typed, scoped plan patches and their deterministic verdict.

Two rules drive this module.

**A patch is not a permission.** The grant comes from the task's trusted
``change_domains`` snapshot, never from the patch body, the model's ``reason`` or
the skill that produced it. A training grant therefore cannot rewrite a meal even
when the patch says so.

**Nothing is applied until everything is valid.** Patches are checked against the
base plan first and only then written into a deep copy, so a bundle containing one
bad patch leaves the base byte-identical. A partially applied candidate would be
a plan nobody validated.

This module computes and checks; it holds no gateway, no repository and no
transaction. Persistence, round accounting and activation live above it.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Domain = Literal["training", "diet"]

# Reviewed exercise vocabulary, aligned with knowledge_base/exercise_library.md.
# Extending content does not require a new per-exercise tool or workflow.
EXERCISE_NAMES = frozenset({
    "深蹲", "箭步蹲", "硬拉", "腿举", "卧推", "俯卧撑", "肩推", "上斜哑铃推举",
    "划船", "引体向上", "高位下拉", "面拉",
    "squat", "lunge", "deadlift", "leg press", "bench press", "push-up", "push-ups",
    "shoulder press", "incline dumbbell press", "row", "pull-up", "lat pulldown", "face pull",
})

# What each reviewed movement needs. Equipment is a hard constraint from trusted
# storage, so a candidate that requires a barbell the user does not have is not
# merely suboptimal -- it cannot be performed. Bodyweight movements need nothing.
EQUIPMENT_TOKENS = frozenset({"barbell", "dumbbell", "machine", "cable", "pull-up bar", "bodyweight"})
EXERCISE_EQUIPMENT: dict[str, str] = {
    "深蹲": "barbell", "squat": "barbell",
    "箭步蹲": "bodyweight", "lunge": "bodyweight",
    "硬拉": "barbell", "deadlift": "barbell",
    "腿举": "machine", "leg press": "machine",
    "卧推": "barbell", "bench press": "barbell",
    "俯卧撑": "bodyweight", "push-up": "bodyweight", "push-ups": "bodyweight",
    "肩推": "dumbbell", "shoulder press": "dumbbell",
    "上斜哑铃推举": "dumbbell", "incline dumbbell press": "dumbbell",
    "划船": "machine", "row": "machine",
    "引体向上": "pull-up bar", "pull-up": "pull-up bar",
    "高位下拉": "machine", "lat pulldown": "machine",
    "面拉": "cable", "face pull": "cable",
}

DAY_TYPES = frozenset({"strength", "cardio", "flexibility", "mobility", "rest", "other"})
INTENSITIES = frozenset({"low", "medium", "high"})

DAY_FIELDS = frozenset({"day", "type", "focus", "intensity", "exercises", "duration_min", "sets", "reps"})
REQUIRED_DAY_FIELDS = frozenset({"day", "type", "focus", "intensity", "exercises"})
EXERCISE_FIELDS = frozenset({"name", "sets", "reps", "rest_seconds", "duration_min", "intensity"})

MAX_PATCHES = 14
MAX_EXERCISES_PER_DAY = 20
MAX_MEAL_CHARS = 200

# The only editable locations in v1: replacing an existing element of these two
# lists. No array growth, no shrinking, no target or validation rewriting.
EDITABLE_LISTS: dict[tuple[str, str], Domain] = {
    ("workout_plan", "days"): "training",
    ("diet_plan", "meals"): "diet",
}

# Target-shaped fields that a candidate may never move. Changing one of these is a
# new task for the user to authorise, not a repair of the current candidate.
PROTECTED_PATHS: dict[str, tuple[str, ...]] = {
    "diet_plan": ("daily_calorie_target", "daily_protein_target", "calories", "protein", "carbs", "fat"),
    "workout_plan": ("weekly_training_days", "rest_days"),
}
PROTECTED_ROOTS = frozenset({"validation", "trace", "targets"})

_MEAL_LINK = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class PlanPatchError(ValueError):
    """A business rejection, not a protocol failure.

    The message is the code so a caller that only catches ``ValueError`` still
    sees the reason. ``domain`` and ``path`` are populated when the rejection can
    be attributed to one patch.
    """

    def __init__(self, code: str, *, domain: str | None = None, path: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.domain = domain
        self.path = path


class Patch(BaseModel):
    """One proposed replacement of one existing plan element."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: Domain
    path: tuple[str | int, ...]
    old_value: Any
    new_value: Any
    reason: str = Field(min_length=1, max_length=200)
    evidence_refs: tuple[str, ...] = ()


class CandidateBundle(BaseModel):
    """The patches submitted for one task round, bounded and strict."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    patches: tuple[Patch, ...] = Field(min_length=1, max_length=MAX_PATCHES)

    def domains(self) -> frozenset[str]:
        return frozenset(patch.domain for patch in self.patches)

    def digest(self) -> str:
        payload = [patch.model_dump(mode="json") for patch in self.patches]
        return _digest(payload)


class Violation(BaseModel):
    """A bounded reason: code, domain and path. Never free text, never private data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=64)
    domain: Domain
    path: str = Field(min_length=1, max_length=120)


class CandidateVerdict(BaseModel):
    """Deterministic answer for one bundle. It is not an activation.

    ``domain_digests`` is what makes "this round did not touch the domain that
    already passed" checkable instead of merely intended: the next round compares
    the recomputed digest against the recorded one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    digest: str
    passed: bool
    failed_domains: tuple[Domain, ...] = ()
    violations: tuple[Violation, ...] = ()
    dependency_digest: str
    domain_digests: tuple[tuple[str, str], ...] = ()


class PlanConstraints(BaseModel):
    """Hard constraints from trusted storage.

    ``None`` means *unknown* and forces a clarification; ``()`` means verified to
    be empty. The difference matters: treating an unknown restriction as "no
    restriction" is how a candidate becomes unsafe while looking validated.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal: str | None = None
    weight_kg: float | None = Field(default=None, gt=0)
    daily_calorie_target: float | None = Field(default=None, ge=0)
    daily_protein_target: float | None = Field(default=None, ge=0)
    allergies_or_restrictions: tuple[str, ...] | None = None
    # Declared medical conditions that affect nutrition (pregnancy, breastfeeding,
    # eating-disorder history, a condition affecting nutrition). Kept as opaque
    # strings rather than the literal enum on purpose: the rule below does not need
    # to know *which* condition it is, and naming them here would make an added
    # code a breaking change for stored tasks.
    safety_conditions: tuple[str, ...] | None = None
    action_restrictions: tuple[str, ...] | None = None
    available_equipment: tuple[str, ...] | None = None
    session_minutes: int | None = Field(default=None, gt=0)
    forbidden_exercises: tuple[str, ...] = ()


def _digest(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _bounded_int(value: Any, low: int, high: int) -> bool:
    return _is_int(value) and low <= value <= high


def _bounded_text(value: Any, low: int, high: int) -> bool:
    return isinstance(value, str) and low <= len(value.strip()) <= high


def _reject_value(code: str, patch: Patch, detail: str) -> None:
    raise PlanPatchError(code, domain=patch.domain, path=detail)


def validate_training_day(value: Any) -> None:
    """Closed shape for a training day. Raises ``PATCH_VALUE_NOT_ALLOWED``."""
    if not isinstance(value, dict):
        raise ValueError("not a mapping")
    if set(value) - DAY_FIELDS:
        raise ValueError("unknown day field")
    if REQUIRED_DAY_FIELDS - set(value):
        raise ValueError("missing day field")
    if not _bounded_text(value["day"], 1, 20):
        raise ValueError("day label")
    if value["type"] not in DAY_TYPES:
        raise ValueError("day type")
    if not _bounded_text(value["focus"], 1, 40):
        raise ValueError("focus")
    if value["intensity"] not in INTENSITIES:
        raise ValueError("intensity")
    for key, low, high in (("duration_min", 5, 300), ("sets", 1, 20), ("reps", 1, 100)):
        if key in value and not _bounded_int(value[key], low, high):
            raise ValueError(key)
    exercises = value["exercises"]
    if not isinstance(exercises, (list, tuple)) or not 1 <= len(exercises) <= MAX_EXERCISES_PER_DAY:
        raise ValueError("exercises")
    for exercise in exercises:
        if not isinstance(exercise, dict):
            raise ValueError("exercise")
        if set(exercise) - EXERCISE_FIELDS:
            raise ValueError("unknown exercise field")
        name = exercise.get("name")
        if not isinstance(name, str) or name.strip().lower() not in EXERCISE_NAMES:
            raise ValueError("exercise name")
        for key, low, high in (("sets", 1, 20), ("reps", 1, 100),
                               ("rest_seconds", 0, 600), ("duration_min", 1, 300)):
            if key in exercise and not _bounded_int(exercise[key], low, high):
                raise ValueError(key)
        if "intensity" in exercise and exercise["intensity"] not in INTENSITIES:
            raise ValueError("exercise intensity")


def validate_meal_text(value: Any) -> None:
    """Bounded plain text. A meal description is not a nutrient fact."""
    if not isinstance(value, str):
        raise ValueError("meal is not text")
    text = value.strip()
    if not 1 <= len(text) <= MAX_MEAL_CHARS:
        raise ValueError("meal length")
    if "<" in text or ">" in text:
        raise ValueError("meal markup")
    if _MEAL_LINK.search(text):
        raise ValueError("meal link")
    if _CONTROL.search(text):
        raise ValueError("meal control character")


def _path_label(path: tuple[str | int, ...]) -> str:
    return ".".join(str(part) for part in path)


def _resolve_patch(base: dict, patch: Patch, change_domains: frozenset[str], seen: set) -> None:
    """Validate one patch against the base plan without touching it."""
    path = patch.path
    if not isinstance(path, tuple) or len(path) < 2:
        raise PlanPatchError("PATCH_PATH_NOT_ALLOWED", domain=patch.domain, path=_path_label(path))
    root, collection = path[0], path[1]
    if not isinstance(root, str) or not isinstance(collection, str):
        raise PlanPatchError("PATCH_PATH_NOT_ALLOWED", domain=patch.domain, path=_path_label(path))
    owner = EDITABLE_LISTS.get((root, collection))
    if owner is None:
        raise PlanPatchError("PATCH_PATH_NOT_ALLOWED", domain=patch.domain, path=_path_label(path))
    if owner != patch.domain:
        # The patch names a domain it is not allowed to edit. This is decided
        # before the path is even checked for arity: a training grant cannot
        # reach a meal, however the path is spelled.
        raise PlanPatchError("PATCH_SCOPE", domain=patch.domain, path=_path_label(path))
    if patch.domain not in change_domains:
        raise PlanPatchError("PATCH_SCOPE", domain=patch.domain, path=_path_label(path))
    if (root, collection, tuple(path[2:])) in seen:
        raise PlanPatchError("PATCH_DUPLICATE", domain=patch.domain, path=_path_label(path))
    if len(path) != 3:
        raise PlanPatchError("PATCH_PATH_NOT_ALLOWED", domain=patch.domain, path=_path_label(path))
    index = path[2]
    if not _is_int(index) or index < 0:
        raise PlanPatchError("PATCH_PATH_NOT_ALLOWED", domain=patch.domain, path=_path_label(path))

    container = base.get(root)
    if not isinstance(container, dict):
        raise PlanPatchError("PLAN_FORMAT_UNSUPPORTED", domain=patch.domain, path=root)
    items = container.get(collection)
    if not isinstance(items, list):
        raise PlanPatchError("PLAN_FORMAT_UNSUPPORTED", domain=patch.domain, path=f"{root}.{collection}")
    if index >= len(items):
        raise PlanPatchError("PATCH_PATH_NOT_ALLOWED", domain=patch.domain, path=_path_label(path))

    current = items[index]
    if current != patch.old_value:
        raise PlanPatchError("PATCH_STALE", domain=patch.domain, path=_path_label(path))

    if patch.domain == "training":
        if not isinstance(current, dict):
            raise PlanPatchError("PLAN_FORMAT_UNSUPPORTED", domain="training", path=_path_label(path))
        try:
            validate_training_day(patch.new_value)
        except ValueError:
            _reject_value("PATCH_VALUE_NOT_ALLOWED", patch, _path_label(path))
    else:
        if not isinstance(current, str):
            # A structured meal is a historical shape: readable, not rewritable by
            # a text patch.
            raise PlanPatchError("PLAN_FORMAT_UNSUPPORTED", domain="diet", path=_path_label(path))
        try:
            validate_meal_text(patch.new_value)
        except ValueError:
            _reject_value("PATCH_VALUE_NOT_ALLOWED", patch, _path_label(path))


def apply_patches(base: dict, patches, change_domains: frozenset[str]) -> dict:
    """Return a new plan with every patch applied, or raise and change nothing."""
    patches = tuple(patches)
    if not patches:
        raise PlanPatchError("PATCH_EMPTY")
    if not isinstance(change_domains, frozenset):
        # An untyped grant would be a grant nobody made.
        raise PlanPatchError("PATCH_SCOPE")
    if not isinstance(base, dict):
        raise PlanPatchError("PLAN_FORMAT_UNSUPPORTED")

    seen: set = set()
    for patch in patches:
        if not isinstance(patch, Patch):
            raise PlanPatchError("PATCH_NOT_TYPED")
        _resolve_patch(base, patch, change_domains, seen)
        seen.add((patch.path[0], patch.path[1], tuple(patch.path[2:])))

    patched = deepcopy(base)
    for patch in patches:
        root, collection, index = patch.path
        patched[root][collection][index] = deepcopy(patch.new_value)
    return patched


def preserves_targets(base: dict, patched: dict) -> tuple[Violation, ...]:
    """Compare the target-shaped fields a candidate must not move."""
    violations: list[Violation] = []
    for root, keys in PROTECTED_PATHS.items():
        before = base.get(root) or {}
        after = patched.get(root) or {}
        if not isinstance(before, dict) or not isinstance(after, dict):
            continue
        for key in keys:
            if before.get(key) != after.get(key):
                violations.append(Violation(code="GOAL_CHANGED", domain="training" if root == "workout_plan" else "diet",
                                            path=f"{root}.{key}"))
    for root in sorted(PROTECTED_ROOTS):
        if base.get(root) != patched.get(root):
            violations.append(Violation(code="GOAL_CHANGED", domain="training", path=root))
    known = set(PROTECTED_PATHS) | PROTECTED_ROOTS
    for key in sorted(set(base) | set(patched)):
        if key not in known and base.get(key) != patched.get(key):
            violations.append(Violation(code="GOAL_CHANGED", domain="training", path=str(key)[:120]))
    return tuple(violations)


# Prefixes are matched, the free text is dropped: a legacy message may quote the
# user's own restriction back at us, and violations travel to the model.
_LEGACY_CODES: tuple[tuple[str, str, str], ...] = (
    ("饮食计划热量明显过低", "CALORIE_TOO_LOW", "diet"),
    ("蛋白质目标和用户体重不匹配", "PROTEIN_TOO_LOW", "diet"),
    ("饮食计划违反用户过敏或限制", "ALLERGEN_CONFLICT", "diet"),
    ("训练频率过高", "TRAINING_FREQUENCY_HIGH", "training"),
    ("训练计划连续安排高强度", "CONSECUTIVE_HIGH_INTENSITY", "training"),
    ("训练计划没有包含休息日", "REST_DAYS_MISSING", "training"),
    ("输出缺少 diet_plan 或 workout_plan 结构", "PLAN_STRUCTURE_MISSING", "training"),
)


def legacy_violations(plan: dict, constraints: PlanConstraints) -> list[Violation]:
    """The reviewed medical thresholds, reused rather than re-derived.

    ``validate_generated_plan`` owns the numbers (calorie floor, protein per
    kilogram, frequency, consecutive intensity, rest days). Re-implementing them
    here would let two validators disagree, so this bridge keeps one source and
    maps its messages to codes. The free text is dropped on purpose: those
    messages quote the user's own restriction back at us, and violations travel
    to the model.
    """
    from backend.agent.validator import validate_generated_plan

    profile = {
        "weight_kg": constraints.weight_kg,
        "daily_calorie_target": constraints.daily_calorie_target,
        "allergies_or_restrictions": list(constraints.allergies_or_restrictions or ()),
    }
    result = validate_generated_plan(plan, profile)
    found: list[Violation] = []
    for message in result.get("violations", ()):
        text = str(message)
        for prefix, code, domain in _LEGACY_CODES:
            if text.startswith(prefix):
                found.append(Violation(code=code, domain=domain, path=_legacy_path(code)))
                break
        else:
            found.append(Violation(code="VALIDATION_VIOLATION", domain="training", path="plan"))
    return found


def _legacy_path(code: str) -> str:
    return {
        "CALORIE_TOO_LOW": "diet_plan.daily_calorie_target",
        "PROTEIN_TOO_LOW": "diet_plan.daily_protein_target",
        "ALLERGEN_CONFLICT": "diet_plan.meals",
        "TRAINING_FREQUENCY_HIGH": "workout_plan.weekly_training_days",
        "CONSECUTIVE_HIGH_INTENSITY": "workout_plan.days",
        "REST_DAYS_MISSING": "workout_plan.rest_days",
        "PLAN_STRUCTURE_MISSING": "plan",
    }.get(code, "plan")


def _required_constraints(domains: frozenset[str], constraints: PlanConstraints) -> list[Violation]:
    """Reasons the candidate cannot be judged at all -- before any value is read.

    Two different refusals share this slot because both must stop the round rather
    than send it back to the model.

    ``CONSTRAINT_MISSING``: the value is unknown, so the check cannot run and the
    task has to ask. Unknown is never treated as empty.

    ``SAFETY_CONDITION_BLOCKS_DIET``: the value is known and it says this account's
    nutrition must not be designed here. The rest of the product already says so --
    ``calculate_daily_targets`` refuses outright for a declared safety condition
    rather than computing a target -- so a model rewriting the meals would be
    doing, unsupervised, the one thing the deterministic path declines to do.
    Training is untouched: the four conditions are nutrition conditions.
    """
    missing: list[Violation] = []
    if "diet" in domains:
        if constraints.allergies_or_restrictions is None:
            missing.append(Violation(code="CONSTRAINT_MISSING", domain="diet",
                                     path="constraints.allergies_or_restrictions"))
        if constraints.safety_conditions is None:
            missing.append(Violation(code="CONSTRAINT_MISSING", domain="diet",
                                     path="constraints.safety_conditions"))
        elif constraints.safety_conditions:
            missing.append(Violation(code="SAFETY_CONDITION_BLOCKS_DIET", domain="diet",
                                     path="constraints.safety_conditions"))
    if "training" in domains and constraints.action_restrictions is None:
        missing.append(Violation(code="CONSTRAINT_MISSING", domain="training",
                                 path="constraints.action_restrictions"))
    return missing


def bundle_identity(base: dict, bundle: CandidateBundle) -> tuple[str, str, str]:
    """``(candidate_id, digest, dependency_digest)`` for one bundle.

    Computed without touching the base, so it is available even when the bundle
    cannot be applied. The dependency digest names what the verdict depended on:
    the domains, the paths and the targets the candidate may not move.
    """
    digest = bundle.digest()
    dependency = _digest({
        "domains": sorted(bundle.domains()),
        "paths": sorted(_path_label(patch.path) for patch in bundle.patches),
        "targets": {key: (base.get(root) or {}).get(key)
                    for root, keys in PROTECTED_PATHS.items() for key in keys}
        if isinstance(base, dict) else {},
    })
    return digest[:32], digest, dependency


def validate_bundle(base: dict, bundle: CandidateBundle, constraints: PlanConstraints,
                    *, change_domains: frozenset[str] = frozenset()) -> CandidateVerdict:
    """Check one bundle end to end and return a bounded verdict.

    ``change_domains`` defaults to the empty grant on purpose: a caller that
    forgets to pass the task's snapshot gets a rejection, not an open door.
    """
    domains = bundle.domains()
    candidate_id, digest, dependency = bundle_identity(base, bundle)

    def verdict(violations: list[Violation]) -> CandidateVerdict:
        failed = tuple(sorted({item.domain for item in violations}, key=lambda d: (d != "training", d)))
        return CandidateVerdict(candidate_id=candidate_id, digest=digest, passed=not violations,
                                failed_domains=failed if violations else (),
                                violations=tuple(violations), dependency_digest=dependency)

    if len(domains) > 1 and not domains <= change_domains:
        unauthorized = [Violation(code="CROSS_DOMAIN_UNAUTHORIZED", domain=domain, path="bundle.domains")
                        for domain in sorted(domains - change_domains)]
        return verdict(unauthorized)

    missing = _required_constraints(domains, constraints)

    try:
        patched = apply_patches(base, bundle.patches, change_domains)
    except PlanPatchError as error:
        return verdict([Violation(code=error.code, domain=error.domain or "training",
                                  path=error.path or "plan")])

    if missing:
        # Authorization is checked first: asking a clarifying question about a
        # patch the task may not submit would leak that the patch was plausible.
        return verdict(missing)

    violations = list(preserves_targets(base, patched))
    if not violations:
        violations = legacy_violations(patched, constraints)
    return verdict(violations)
