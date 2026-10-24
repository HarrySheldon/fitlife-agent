"""Scoped patch behaviour: a patch may only touch what the task was granted.

Every rejection here is a business answer, not a protocol failure. The point of
the module is that the same patch text can be refused for a domain the user did
not authorize while the base plan stays byte-identical.
"""
from copy import deepcopy

import pytest

from backend.domain.plan_adjustment import (
    CandidateBundle,
    PlanConstraints,
    PlanPatchError,
    Patch,
    apply_patches,
    preserves_targets,
    validate_bundle,
)


def _training_day(**overrides):
    day = {
        "day": "周一",
        "type": "strength",
        "focus": "胸",
        "intensity": "medium",
        "exercises": [{"name": "卧推", "sets": 3, "reps": 8, "rest_seconds": 90}],
        "duration_min": 45,
    }
    day.update(overrides)
    return day


def _plan():
    return {
        "workout_plan": {
            "summary": "每周三次全身训练",
            "weekly_training_days": 3,
            "rest_days": ["周日"],
            "days": [_training_day()],
            "notes": "",
        },
        "diet_plan": {
            "summary": "维持热量，蛋白质优先",
            "daily_calorie_target": 2000,
            "daily_protein_target": 140,
            "meals": ["燕麦加鸡蛋", "鸡胸肉沙拉", "牛肉面"],
        },
        "validation": {"passed": True},
    }


def _training_patch(**overrides):
    values = {
        "domain": "training",
        "path": ("workout_plan", "days", 0),
        "old_value": _training_day(),
        "new_value": _training_day(intensity="high"),
        "reason": "用户希望提高强度",
        "evidence_refs": (),
    }
    values.update(overrides)
    return Patch(**values)


def test_training_grant_does_not_authorize_diet_change():
    base = {"workout_plan": {"days": []}, "diet_plan": {"meals": ["original"]}}
    before = deepcopy(base)
    patch = Patch(domain="training", path=("diet_plan", "meals"),
                  old_value=["original"], new_value=["changed"],
                  reason="wrong domain", evidence_refs=())
    with pytest.raises(ValueError, match="PATCH_SCOPE"):
        apply_patches(base, (patch,), frozenset({"training"}))
    assert base == before


def test_patch_that_changes_only_training_leaves_diet_deep_equal():
    base = _plan()
    diet_before = deepcopy(base["diet_plan"])

    patched = apply_patches(base, (_training_patch(),), frozenset({"training"}))

    assert patched["diet_plan"] == diet_before
    assert patched["workout_plan"]["days"][0]["intensity"] == "high"
    # The input is never mutated in place.
    assert base["workout_plan"]["days"][0]["intensity"] == "medium"


def test_change_domain_grant_is_checked_separately_from_read_domain():
    # Reading diet is not permission to write diet.
    base = _plan()
    patch = Patch(domain="diet", path=("diet_plan", "meals", 0),
                  old_value="燕麦加鸡蛋", new_value="全麦面包加鸡蛋",
                  reason="换主食", evidence_refs=())

    with pytest.raises(ValueError, match="PATCH_SCOPE"):
        apply_patches(base, (patch,), frozenset({"training"}))


def test_stale_old_value_is_rejected_instead_of_overwriting():
    base = _plan()
    patch = _training_patch(old_value=_training_day(intensity="low"))

    with pytest.raises(ValueError, match="PATCH_STALE"):
        apply_patches(base, (patch,), frozenset({"training"}))


def test_duplicate_path_is_rejected_before_any_patch_is_applied():
    base = _plan()
    before = deepcopy(base)
    patches = (_training_patch(), _training_patch())

    with pytest.raises(ValueError, match="PATCH_DUPLICATE"):
        apply_patches(base, patches, frozenset({"training"}))
    assert base == before


def test_one_invalid_patch_means_no_patch_is_applied():
    base = _plan()
    before = deepcopy(base)
    good = _training_patch()
    bad = Patch(domain="diet", path=("diet_plan", "meals", 9),
                old_value="不存在", new_value="任意", reason="越界", evidence_refs=())

    with pytest.raises(ValueError, match="PATCH_PATH_NOT_ALLOWED"):
        apply_patches(base, (good, bad), frozenset({"training", "diet"}))
    assert base == before


@pytest.mark.parametrize("path", [
    ("workout_plan", "days", -1),
    ("workout_plan", "days", 5),
    ("workout_plan", "days"),
    ("workout_plan", "weekly_training_days"),
    ("diet_plan", "daily_calorie_target"),
    ("validation", "passed"),
    ("/workout_plan/days/0",),
])
def test_only_existing_list_index_replacement_is_allowed(path):
    base = _plan()
    patch = Patch(domain="training", path=path, old_value=None, new_value=None,
                  reason="越界路径", evidence_refs=())

    with pytest.raises(ValueError, match="PATCH_PATH_NOT_ALLOWED"):
        apply_patches(base, (patch,), frozenset({"training", "diet"}))


def test_empty_bundle_is_not_a_candidate():
    with pytest.raises(ValueError, match="PATCH_EMPTY"):
        apply_patches(_plan(), (), frozenset({"training"}))


def test_training_day_rejects_unknown_fields_and_bad_numbers():
    base = _plan()
    with_extra = _training_day(mood="开心")
    patch = _training_patch(new_value=with_extra)
    with pytest.raises(ValueError, match="PATCH_VALUE_NOT_ALLOWED"):
        apply_patches(base, (patch,), frozenset({"training"}))

    negative = _training_day(duration_min=-30)
    patch = _training_patch(new_value=negative)
    with pytest.raises(ValueError, match="PATCH_VALUE_NOT_ALLOWED"):
        apply_patches(base, (patch,), frozenset({"training"}))


def test_training_day_rejects_unreviewed_exercise_vocabulary():
    base = _plan()
    invented = _training_day(exercises=[{"name": "量子卧推", "sets": 3, "reps": 8, "rest_seconds": 60}])
    patch = _training_patch(new_value=invented)

    with pytest.raises(ValueError, match="PATCH_VALUE_NOT_ALLOWED"):
        apply_patches(base, (patch,), frozenset({"training"}))


def test_training_day_rejects_unknown_enum_values():
    base = _plan()
    patch = _training_patch(new_value=_training_day(intensity="maximum"))
    with pytest.raises(ValueError, match="PATCH_VALUE_NOT_ALLOWED"):
        apply_patches(base, (patch,), frozenset({"training"}))

    patch = _training_patch(new_value=_training_day(type="crossfit"))
    with pytest.raises(ValueError, match="PATCH_VALUE_NOT_ALLOWED"):
        apply_patches(base, (patch,), frozenset({"training"}))


@pytest.mark.parametrize("meal", [
    "<b>鸡胸肉</b>沙拉",
    "参见 https://example.com/diet",
    "更多内容见 www.example.com",
])
def test_meal_text_cannot_smuggle_markup_or_links(meal):
    base = _plan()
    patch = Patch(domain="diet", path=("diet_plan", "meals", 1),
                  old_value="鸡胸肉沙拉", new_value=meal, reason="替换", evidence_refs=())

    with pytest.raises(ValueError, match="PATCH_VALUE_NOT_ALLOWED"):
        apply_patches(base, (patch,), frozenset({"diet"}))


def test_legacy_plan_stays_readable_but_refuses_automatic_adjustment():
    # A dict-shaped meal entry is a historical structure we can read but must not
    # rewrite through a text patch.
    base = _plan()
    base["diet_plan"]["meals"] = [{"food": "燕麦", "calories": 300}]
    patch = Patch(domain="diet", path=("diet_plan", "meals", 0),
                  old_value={"food": "燕麦", "calories": 300}, new_value="燕麦",
                  reason="替换", evidence_refs=())

    with pytest.raises(ValueError, match="PLAN_FORMAT_UNSUPPORTED"):
        apply_patches(base, (patch,), frozenset({"diet"}))


def test_missing_workout_days_structure_is_unsupported_not_empty():
    base = _plan()
    base["workout_plan"]["days"] = {"周一": _training_day()}
    patch = _training_patch()

    with pytest.raises(ValueError, match="PLAN_FORMAT_UNSUPPORTED"):
        apply_patches(base, (patch,), frozenset({"training"}))


def test_targets_are_preserved_by_construction():
    base = _plan()
    patched = apply_patches(base, (_training_patch(),), frozenset({"training"}))

    assert preserves_targets(base, patched) == ()
    assert patched["diet_plan"]["daily_calorie_target"] == 2000
    assert patched["workout_plan"]["weekly_training_days"] == 3
    assert patched["validation"] == {"passed": True}


def test_target_drift_is_reported_with_a_bounded_code():
    base = _plan()
    patched = deepcopy(base)
    patched["diet_plan"]["daily_calorie_target"] = 1200

    violations = preserves_targets(base, patched)

    assert [item.code for item in violations] == ["GOAL_CHANGED"]
    assert violations[0].path == "diet_plan.daily_calorie_target"


def test_bundle_is_bounded_and_strict():
    with pytest.raises(Exception):
        CandidateBundle(patches=tuple(_training_patch() for _ in range(15)))
    with pytest.raises(Exception):
        CandidateBundle(patches=(_training_patch(),), extra_field="nope")


def test_verdict_passes_for_an_in_scope_candidate():
    base = _plan()
    bundle = CandidateBundle(patches=(_training_patch(),))
    constraints = PlanConstraints(
        goal="build_muscle", weight_kg=70, daily_calorie_target=2000,
        daily_protein_target=140, allergies_or_restrictions=(),
        action_restrictions=(), available_equipment=("barbell",),
    )

    verdict = validate_bundle(base, bundle, constraints, change_domains=frozenset({"training"}))

    assert verdict.passed is True
    assert verdict.failed_domains == ()
    assert verdict.violations == ()
    assert verdict.digest == bundle.digest()
    assert verdict.candidate_id == verdict.digest[:32]


def test_verdict_reports_allergen_conflict_without_echoing_the_restriction():
    base = _plan()
    patch = Patch(domain="diet", path=("diet_plan", "meals", 1),
                  old_value="鸡胸肉沙拉", new_value="花生酱鸡胸肉沙拉",
                  reason="增加风味", evidence_refs=())
    bundle = CandidateBundle(patches=(patch,))
    constraints = PlanConstraints(
        goal="fat_loss", weight_kg=70, daily_calorie_target=2000,
        daily_protein_target=140, allergies_or_restrictions=("花生",),
    )

    verdict = validate_bundle(base, bundle, constraints, change_domains=frozenset({"diet"}))

    assert verdict.passed is False
    assert "diet" in verdict.failed_domains
    codes = [item.code for item in verdict.violations]
    assert "ALLERGEN_CONFLICT" in codes
    # Bounded codes only: the restriction term itself must not travel back.
    assert all("花生" not in str(item.code) for item in verdict.violations)
    assert all(set(item.model_dump()) == {"code", "domain", "path"} for item in verdict.violations)


def test_verdict_asks_for_missing_restrictions_instead_of_assuming_none():
    base = _plan()
    bundle = CandidateBundle(patches=(_training_patch(),))
    constraints = PlanConstraints(goal="build_muscle", weight_kg=70,
                                 daily_calorie_target=2000, daily_protein_target=140)

    verdict = validate_bundle(base, bundle, constraints, change_domains=frozenset({"training"}))

    assert verdict.passed is False
    assert {item.code for item in verdict.violations} == {"CONSTRAINT_MISSING"}


def test_verdict_defaults_to_no_write_grant():
    bundle = CandidateBundle(patches=(_training_patch(),))
    constraints = PlanConstraints(goal="build_muscle", weight_kg=70,
                                 daily_calorie_target=2000, daily_protein_target=140,
                                 allergies_or_restrictions=())

    verdict = validate_bundle(_plan(), bundle, constraints)

    assert verdict.passed is False
    assert [item.code for item in verdict.violations] == ["PATCH_SCOPE"]


def test_verdict_surfaces_out_of_scope_patches_as_business_feedback():
    base = _plan()
    bundle = CandidateBundle(patches=(_training_patch(),))

    verdict = validate_bundle(base, bundle, PlanConstraints(), change_domains=frozenset({"diet"}))

    assert verdict.passed is False
    assert "PATCH_SCOPE" in [item.code for item in verdict.violations]


def test_verdict_rejects_a_bundle_that_mixes_unauthorized_domains():
    base = _plan()
    diet_patch = Patch(domain="diet", path=("diet_plan", "meals", 0),
                       old_value="燕麦加鸡蛋", new_value="全麦面包加鸡蛋",
                       reason="换主食", evidence_refs=())
    bundle = CandidateBundle(patches=(_training_patch(), diet_patch))

    verdict = validate_bundle(base, bundle, PlanConstraints(), change_domains=frozenset({"training"}))

    assert verdict.passed is False
    assert "CROSS_DOMAIN_UNAUTHORIZED" in [item.code for item in verdict.violations]


def test_patch_error_carries_the_code_and_is_a_value_error():
    with pytest.raises(PlanPatchError) as caught:
        apply_patches(_plan(), (_training_patch(old_value=_training_day(intensity="low")),),
                      frozenset({"training"}))
    assert caught.value.code == "PATCH_STALE"
    assert isinstance(caught.value, ValueError)
