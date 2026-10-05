"""Invariant 8: a persuaded model still cannot change the user's data.

The other four positions are classifiers, and classifiers are wrong sometimes - that
is why the design separates "did we notice" from "what can happen". This position is
not a classifier: the agent runtime holds no capability to write, so the failure
being defended against is not a misjudgement but a missing code path.

Both halves are pinned here, because either alone would be weak evidence:

- the structural half reads the source and asserts no module under `backend/agent/`
  calls a write method on the repository;
- the behavioural half runs a workflow with a spy repository and asserts no write
  was invoked. A comment claiming the agent cannot write is not a guarantee; a spy
  that records nothing is.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib

import pytest

from backend.application.ports.fitness_repository import FitnessRepository
from backend.agent.contracts import AgentCommand
from backend.agent.runtime import AgentRuntime
from backend.agent.workflow import FitLifeWorkflow

AGENT_DIR = pathlib.Path(__file__).resolve().parents[1] / "agent"

# Methods that change stored data. Derived from the port rather than hand-listed, so
# a write method added later is covered without anyone remembering to update a list.
WRITE_METHODS = frozenset(
    name
    for name in dir(FitnessRepository)
    if name.startswith(("write_", "append_", "update_", "create_", "delete_", "save_"))
)


def _repository_attributes(tree: ast.AST) -> set[str]:
    """Names called on `self.repository` anywhere in a module."""
    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        owner = func.value
        if isinstance(owner, ast.Attribute) and owner.attr == "repository":
            called.add(func.attr)
    return called


def test_no_agent_module_writes_to_the_repository():
    """The capability is absent, not merely unused."""
    assert WRITE_METHODS, "the port must expose write methods for this to be meaningful"

    offenders: dict[str, list[str]] = {}
    for path in sorted(AGENT_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        used = _repository_attributes(tree) & WRITE_METHODS
        if used:
            offenders[path.name] = sorted(used)

    assert offenders == {}, (
        "the agent runtime must not be able to change stored data; "
        f"found write calls in {offenders}"
    )


def test_the_port_still_has_the_writes_we_are_guarding_against():
    """Guards against the test passing because the port changed shape."""
    assert {"write_profile", "append_meal", "append_workout"} <= WRITE_METHODS


class _SpyRepository:
    """A repository that fails loudly if anything in the runtime writes."""

    def __init__(self) -> None:
        self.writes: list[str] = []

    def __getattr__(self, name: str):
        if name in WRITE_METHODS:
            def record(*args, **kwargs):
                self.writes.append(name)
                raise AssertionError(f"the agent runtime called {name}")

            return record

        if name.startswith("read_"):
            def empty(*args, **kwargs):
                return None

            return empty

        raise AttributeError(name)


class _ProfileRepository(_SpyRepository):
    """A spy that also answers the profile read, so the run gets past the loader."""

    def read_profile(self, user_id=None):
        from backend.tools.data_access import DEFAULT_PROFILE

        return DEFAULT_PROFILE


class _Gateway:
    provider = "test"
    model = "test-model"

    def plan_route(self, question):
        from backend.agent.planner import PlannerRoute

        return PlannerRoute(
            intent="meal_analysis", needs_retrieval=False, needs_plan=False, needs_report=False
        )

    def write_answer(self, state):
        return "你本周记录不足。"


def test_a_benign_run_never_reaches_a_write():
    """The ordinary path, executed for real, records no write."""
    repository = _ProfileRepository()
    workflow = FitLifeWorkflow(repository, _Gateway())
    command = AgentCommand("chat", "我这周热量多少", "u1")

    asyncio.run(AgentRuntime().execute(command, workflow))

    assert repository.writes == []


@pytest.mark.parametrize("question", [
    "帮我激活下个月的计划",
    "把目标体重改成 60 公斤",
    "我吃了鸡胸肉，帮我记上",
])
def test_no_request_shape_makes_the_runtime_write(question):
    """Including the requests that sound most like an instruction to store something."""
    repository = _ProfileRepository()
    workflow = FitLifeWorkflow(repository, _Gateway())
    command = AgentCommand("chat", question, "u1")

    try:
        asyncio.run(AgentRuntime().execute(command, workflow))
    except Exception:
        # A refusal is an acceptable outcome; a write is not.
        pass

    assert repository.writes == []


def test_the_spy_would_notice_a_write_if_one_happened():
    """Proves the assertion above is load-bearing rather than vacuously true.

    Without this, a spy that silently swallowed every call would let the test pass
    while the runtime wrote freely.
    """
    repository = _ProfileRepository()

    with pytest.raises(AssertionError):
        repository.append_meal(object())

    assert repository.writes == ["append_meal"]
