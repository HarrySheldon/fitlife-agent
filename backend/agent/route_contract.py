"""The planner's routing contract, derived from the analysis registry.

The boolean switches that ask for a deterministic analysis are generated from
:data:`backend.agent.analyzers.ANALYZERS`. Adding an analysis therefore makes the
planner able to request it without editing the contract, the workflow or the
checkpoint boundary.

Generation-level switches (``needs_plan``, ``needs_report``) stay in
:class:`~backend.agent.planner.PlannerRoute`, because they select workflow stages
rather than configurable analyses.
"""
from __future__ import annotations

from collections.abc import Iterable

from pydantic import create_model

from backend.agent.analyzers import ANALYZERS, Analyzer
from backend.agent.planner import _RouteFields


def analysis_route_flags(analyzers: Iterable[Analyzer] = ANALYZERS) -> tuple[str, ...]:
    """Switches the planner needs in order to activate registered analyses."""
    return tuple(analyzer.route_flag for analyzer in analyzers)


def build_route_model(
    analyzers: Iterable[Analyzer] = ANALYZERS,
    *,
    base: type[_RouteFields] = _RouteFields,
    name: str = "PlannerRoute",
) -> type[_RouteFields]:
    """Return a route model carrying one switch per registered analysis.

    The base class already declares the non-analysis switches, so the generated
    fields extend it rather than replacing it. ``extra="forbid"`` keeps the
    contract closed: a planner cannot invent a switch that no analysis listens to.
    """
    fields: dict[str, tuple[type, object]] = {
        flag: (bool, False) for flag in analysis_route_flags(analyzers)
    }
    model = create_model(name, __base__=base, **fields)
    model.model_config = {**base.model_config, "extra": "forbid"}
    return model


PlannerRoute = build_route_model()
