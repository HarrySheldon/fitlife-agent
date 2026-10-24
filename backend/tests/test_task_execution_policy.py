"""Execution facts are produced by the application, never by the model.

The stage-A rule is deliberately boring: an optimized plan is identical to the
reference plan until a shortcut is both registered and justified by verified
facts. A test that expected a shortcut here would be asserting a saving nobody
has measured.
"""
import pytest

from backend.agent.tasks.execution_policy import (
    REGISTERED_TRUSTED_ACTIONS,
    STRATEGIES,
    TaskFacts,
    plan_execution,
)


def _facts(**overrides):
    values = dict(task_kind="coach_chat", trusted_action="explain_today",
                  fields_complete=True, catalog_unambiguous=True,
                  scope_verified=True, constraints_complete=True)
    values.update(overrides)
    return TaskFacts(**values)


def test_only_two_strategies_exist():
    assert STRATEGIES == frozenset({"reference", "optimized"})


def test_reference_never_takes_a_shortcut():
    plan = plan_execution("reference", _facts())
    assert plan.use_shortcut is False
    assert plan.reasons == ("reference_strategy",)


def test_stage_a_registers_no_trusted_action_so_optimized_stays_equivalent():
    assert REGISTERED_TRUSTED_ACTIONS == frozenset()
    plan = plan_execution("optimized", _facts())
    assert plan.use_shortcut is False
    assert plan.reasons == ("action_not_registered",)


def test_unverified_scope_blocks_the_shortcut():
    plan = plan_execution("optimized", _facts(scope_verified=False))
    assert plan.use_shortcut is False
    assert "scope_not_verified" in plan.reasons


def test_missing_trusted_action_blocks_the_shortcut():
    plan = plan_execution("optimized", _facts(trusted_action=None))
    assert plan.use_shortcut is False
    assert plan.reasons == ("no_trusted_action",)


def test_incomplete_facts_block_the_shortcut():
    plan = plan_execution("optimized", _facts(constraints_complete=False))
    assert plan.use_shortcut is False
    assert plan.reasons == ("facts_incomplete",)


def test_an_unknown_strategy_is_rejected():
    with pytest.raises(ValueError):
        plan_execution("turbo", _facts())


def test_an_unknown_task_kind_is_rejected():
    with pytest.raises(ValueError):
        TaskFacts("guess")


def test_a_trusted_action_must_be_a_registered_identifier_not_free_text():
    with pytest.raises(ValueError):
        TaskFacts("coach_chat", trusted_action="explain today please")
    with pytest.raises(ValueError):
        TaskFacts("coach_chat", trusted_action="Explain_Today")


def test_deterministic_requires_verified_scope_and_complete_facts():
    assert _facts().deterministic is True
    assert _facts(scope_verified=False).deterministic is False
    assert _facts(fields_complete=False).deterministic is False
    assert _facts(constraints_complete=False).deterministic is False
