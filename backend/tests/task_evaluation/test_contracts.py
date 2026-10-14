"""Contract tests for the scenario model and the deterministic scorer."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.task_evaluation.contracts import Scenario, Step
from backend.task_evaluation.scorers import Score, score_state


@pytest.mark.parametrize("path", ["//evil.test/x", "https://evil.test", "/\\evil", "relative", "/../x", "/x\n"])
def test_step_rejects_nonlocal_paths(path):
    with pytest.raises(ValidationError):
        Step(method="GET", path=path)


def test_suite_validates_all_cases_and_unique_ids():
    from backend.task_evaluation.contracts import Suite
    case = {"id": "x", "version": 1}
    assert len(Suite.model_validate({"schema_version": 1, "scenarios": [case]}).scenarios) == 1
    for payload in [
        {"schema_version": 2, "scenarios": [case]},
        {"schema_version": 1, "scenarios": [case, case]},
        {"schema_version": 1, "scenarios": [case, {"id": "bad", "version": 0}]},
    ]:
        with pytest.raises(ValidationError):
            Suite.model_validate(payload)


def test_structured_references_and_invalid_reference_shapes():
    assert Step(method="POST", path="/x", body={"id": {"$ref": "draft_id"}}, headers={"If-Match": {"$ref": "version"}})
    for value in [{"$ref": ""}, {"$ref": "x", "extra": 1}, {"$ref": 1}]:
        with pytest.raises(ValidationError):
            Step(method="POST", path="/x", body={"id": value})


def test_future_seeds_are_explicitly_reserved():
    with pytest.raises(ValidationError):
        Scenario(id="x", version=1, initial_state={"records": {"import_file": "x"}})


def test_catalog_rejects_unknown_or_incomplete_rows():
    with pytest.raises(ValidationError):
        Scenario(id="x", version=1, initial_state={"catalog": {"foods": [{"name": "rice", "file": "x"}]}})


def test_score_compares_nested_types_without_bool_number_coercion():
    assert not score_state({"a": {"items": [True]}}, {"a": {"items": [1]}}).passed
    assert score_state({"a": {"items": [1]}}, {"a": {"items": [1]}}).passed


def test_declared_seed_capabilities_validate_structured_shapes():
    scenario = Scenario(id="seeded", version=1, initial_state={
        "records": {"meals": [{"log_date": "2026-01-01", "name": "Lunch", "meal_type": "lunch"}]},
        "plans": {"active_count": 1, "draft_count": 2},
        "authorization": {"additional_users": ["other_user"]},
        "faults": {"expire_drafts": True, "sleep_seconds": 1},
    }, steps=[{"actor": "other_user", "method": "PUT", "path": "/profile"}], requires=["future-feature"])
    assert scenario.initial_state.records.meals[0].name == "Lunch"
    assert scenario.steps[0].actor == "other_user"
    for seed in [{"plans": {"active_count": 2}}, {"authorization": {"additional_users": ["primary"]}}, {"faults": {"sleep_seconds": float("inf")}}]:
        with pytest.raises(ValidationError):
            Scenario(id="x", version=1, initial_state=seed)


def test_profile_version_and_catalog_fields_match_seed_apis():
    scenario = Scenario(id="x", version=1, initial_state={
        "profile": {"age": 30, "energy_parameter": "neutral", "activity_level": "moderate", "effective_from": "2026-01-01T00:00:00Z"},
        "catalog": {
            "foods": [{"source_record_id": "rice", "name": "rice", "calories": 100, "carbs": 20, "protein": 3, "fat": 1}],
            "exercises": [{"source_record_id": "run", "name": "run", "exercise_type": "cardio", "primary_muscle": "legs", "met": 8}],
        },
    })
    assert scenario.initial_state.catalog.foods[0].source_name == "task-eval-synthetic"
    assert scenario.initial_state.profile.energy_parameter == "neutral"


def test_scenario_limits_and_boolean_versions_are_rejected():
    from backend.task_evaluation.contracts import Suite
    for version in [0, -1, True]:
        with pytest.raises(ValidationError):
            Scenario(id="x", version=version)
    with pytest.raises(ValidationError):
        Suite(schema_version=True, scenarios=[])
    with pytest.raises(ValidationError):
        Scenario(id="x", version=1, steps=[{"method": "GET", "path": "/x"}] * 101)


def test_dictionary_header_must_be_a_reference():
    with pytest.raises(ValidationError):
        Step(method="GET", path="/x", headers={"If-Match": {"unexpected": "value"}})


@pytest.mark.parametrize("field,value", [
    ("goal", "unknown"), ("weekly_training_frequency", 8),
    ("weekly_training_frequency", -1), ("target_weight_kg", 29),
    ("target_weight_kg", 301), ("daily_calorie_target", 799),
    ("daily_calorie_target", 6001), ("daily_protein_target", 19),
    ("daily_protein_target", 401),
])
def test_legacy_profile_seed_matches_api_ranges(field, value):
    with pytest.raises(ValidationError):
        Scenario(id="x", version=1, initial_state={"profile": {field: value}})


def test_expected_state_is_not_keyword_success():
    scenario = Scenario.model_validate({
        "id": "entry-confirm", "version": 1,
        "steps": [], "expected": {"saved_count": 2},
    })
    assert not score_state(scenario.expected, {"saved_count": 0}).passed


def test_expected_state_passes_when_all_fields_match():
    scenario = Scenario.model_validate({
        "id": "entry-confirm", "version": 1,
        "steps": [], "expected": {"saved_count": 2},
    })
    assert score_state(scenario.expected, {"saved_count": 2, "extra": "ignored"}).passed


def test_a_missing_field_fails_and_is_named():
    score = score_state({"a": 1, "b": 2}, {"a": 1})

    assert not score.passed
    assert score.failed_fields == ("b",)


def test_a_missing_field_is_not_treated_as_equal_to_none():
    """`k not in actual` must fail; it must not be coerced to None == None."""
    assert score_state({"a": None}, {}).failed_fields == ("a",)
    assert not score_state({"a": None}, {"a": None}).failed_fields


def test_a_missing_observation_result_fails():
    """An unobserved outcome is a failure, not a pass and not a silent None."""
    score = score_state({"result": "saved"}, {})

    assert not score.passed
    assert score.failed_fields == ("result",)


def test_step_capture_and_reference_shape():
    step = Step.model_validate({
        "method": "POST",
        "path": "/smart-entry/{draft_id}/confirm",
        "expected_status": 200,
        "capture": {"record_ids": "data.record_ids"},
    })

    assert step.method == "POST"
    assert step.capture == {"record_ids": "data.record_ids"}


def test_scenario_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        Scenario.model_validate({
            "id": "x", "version": 1, "steps": [], "expected": {},
            "not_a_real_field": True,
        })


def test_scenario_requires_id_and_version():
    with pytest.raises(ValidationError):
        Scenario.model_validate({"steps": [], "expected": {}})


def test_initial_state_accepts_only_declared_seed_types():
    """Initial state must be structured data, never an arbitrary file import."""
    scenario = Scenario.model_validate({
        "id": "x", "version": 1, "steps": [], "expected": {},
        "initial_state": {"profile": {"weight_kg": 72}},
    })
    assert scenario.initial_state.profile.weight_kg == 72

    with pytest.raises(ValidationError):
        Scenario.model_validate({
            "id": "x", "version": 1, "steps": [], "expected": {},
            "initial_state": {"profile": "C:\\some\\file.json"},
        })
