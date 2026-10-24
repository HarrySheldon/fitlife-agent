"""The published tool set: reviewed once, fixed for the process.

There is deliberately no ``register`` function. A tool becomes available by being
listed here and passing review, not by being installed at runtime, so nothing a
model says can widen the set.
"""
from backend.agent.tools.contracts import (
    SkillSearchArgs, ResourceReadArgs, QueryArgs, KnowledgeSearchArgs, CalculateArgs,
)
from backend.agent.tools.handlers import PROFILE_FIELDS, calculate
from backend.agent.tools.spec import ToolSpec


def _query_domains(args: QueryArgs) -> frozenset[str]:
    required = {args.domain}
    if args.domain == "profile":
        # A profile field belongs to the domain that owns it, so asking for a
        # diet target requires the diet grant even though the row is "profile".
        required.update(PROFILE_FIELDS.get(field, "invalid") for field in args.fields)
    return frozenset(required)


def _calculate_domains(args: CalculateArgs) -> frozenset[str]:
    if args.operation == "validate_training":
        return frozenset()
    return frozenset({"training" if args.operation == "workout_analysis" else "diet"})


SPECS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            name="skills.search",
            args_model=SkillSearchArgs,
            effect="public_read",
            handler=lambda args, ctx: ctx.catalog.search(args.query, args.limit),
            cacheable=True,
        ),
        ToolSpec(
            name="resources.read",
            args_model=ResourceReadArgs,
            effect="public_read",
            handler=lambda args, ctx: ctx.catalog.read(args.resource_id),
        ),
        ToolSpec(
            name="fitness.query",
            args_model=QueryArgs,
            effect="private_read",
            required_domains=_query_domains,
            handler=lambda args, ctx: ctx.reads.query(args, ctx.domains),
        ),
        ToolSpec(
            name="knowledge.search",
            args_model=KnowledgeSearchArgs,
            effect="public_read",
            # Local knowledge only: health records never leave for a remote
            # embedding or search request.
            handler=lambda args, ctx: ctx.retriever(args.query, args.top_k, scope=args.scope),
        ),
        ToolSpec(
            name="fitness.calculate",
            args_model=CalculateArgs,
            effect="calculate",
            required_domains=_calculate_domains,
            handler=lambda args, ctx: calculate(args, ctx.evidence, ctx.language),
        ),
    )
}


def tool_descriptions(specs=None):
    published = SPECS if specs is None else specs
    return tuple(published[name].describe() for name in sorted(published))
