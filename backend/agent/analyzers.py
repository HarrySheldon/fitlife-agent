"""Declarative registry of the deterministic analyses an answer can be built from.

An analysis reads the user's records and computes metrics. It never writes formal
records and never calls a model, so its numbers are reproducible and auditable.

Adding a domain to the product means adding an :class:`Analyzer` and one entry in
:data:`ANALYZERS`. The workflow iterates this registry instead of branching on
each domain by name, so a new analysis does not require editing the pipeline.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from backend.tools.meal_analyzer import analyze_meals
from backend.tools.workout_analyzer import analyze_workouts

if TYPE_CHECKING:  # imported for typing only: this module must stay loadable early
    from backend.application.ports.fitness_repository import FitnessRepository


class AnalysisContext(Protocol):
    """What an analysis is allowed to read.

    Deliberately narrow: an analysis gets a repository, the user it belongs to,
    and the loaded profile. It has no model gateway and no write path.
    """

    @property
    def repository(self) -> "FitnessRepository": ...

    @property
    def user_id(self) -> str | None: ...

    @property
    def profile(self) -> Mapping[str, object]: ...


@dataclass(frozen=True)
class Analyzer:
    """One deterministic analysis, described as data."""

    id: str
    """Stable identity used in tool traces."""

    route_flag: str
    """The planner flag that activates this analysis."""

    provides: str
    """The ``tool_results`` key this analysis writes."""

    run: Callable[[AnalysisContext], Mapping[str, object]]
    """The deterministic computation."""

    requires: tuple[str, ...] = ()
    """State keys that must exist before this analysis runs."""

    knowledge_scope: tuple[str, ...] = ()
    """Knowledge documents that may ground an answer about this analysis."""

    title: str = ""
    """Human-readable name, used in payloads the model reads."""

    def __post_init__(self) -> None:
        if not self.id or not self.route_flag or not self.provides:
            raise ValueError("An analyzer needs an id, a route flag and an output key")


def run_meal_analysis(context: AnalysisContext) -> Mapping[str, object]:
    profile = context.profile
    return analyze_meals(
        context.repository.read_meals(context.user_id),
        calorie_target=profile["daily_calorie_target"],
        protein_target=profile["daily_protein_target"],
    )


def run_workout_analysis(context: AnalysisContext) -> Mapping[str, object]:
    return analyze_workouts(context.repository.read_workouts(context.user_id))


MEAL_ANALYSIS = Analyzer(
    id="analyze_meals",
    route_flag="needs_meal_analysis",
    provides="meal_analysis",
    requires=("profile",),
    run=run_meal_analysis,
    knowledge_scope=("nutrition_guidelines.md", "meal_templates.md"),
    title="meal analysis",
)

WORKOUT_ANALYSIS = Analyzer(
    id="analyze_workouts",
    route_flag="needs_workout_analysis",
    provides="workout_analysis",
    requires=("profile",),
    run=run_workout_analysis,
    knowledge_scope=("fitness_rules.md", "exercise_library.md"),
    title="workout analysis",
)


ANALYZERS: tuple[Analyzer, ...] = (MEAL_ANALYSIS, WORKOUT_ANALYSIS)


@dataclass(frozen=True)
class AnalyzerRegistry:
    """The analyses available to a run."""

    analyzers: tuple[Analyzer, ...] = field(default_factory=lambda: ANALYZERS)

    def __iter__(self):
        return iter(self.analyzers)

    def activated_by(self, route: Mapping[str, object]) -> tuple[Analyzer, ...]:
        """Return the analyses the planner asked for, preserving registry order."""
        return tuple(analyzer for analyzer in self.analyzers if route.get(analyzer.route_flag))

    def knowledge_scope(self, route: Mapping[str, object]) -> tuple[str, ...]:
        """Knowledge documents belonging to the activated analyses."""
        scope: list[str] = []
        for analyzer in self.activated_by(route):
            for document in analyzer.knowledge_scope:
                if document not in scope:
                    scope.append(document)
        return tuple(scope)

    def ids(self) -> tuple[str, ...]:
        return tuple(analyzer.id for analyzer in self.analyzers)
