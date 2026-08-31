from __future__ import annotations

from collections.abc import Callable

from backend.agent.contracts import AgentCommand, AgentResult
from backend.agent.generator import generate_plan
from backend.agent.runtime import RuntimeContext
from backend.agent.state import AgentState
from backend.agent.validator import validate_generated_plan
from backend.application.ports.fitness_repository import FitnessRepository
from backend.application.ports.model_gateway import ModelGateway
from backend.domain.errors import ApplicationError, model_gateway_error
from backend.rag.retriever import retrieve_knowledge
from backend.tools.meal_analyzer import analyze_meals
from backend.tools.report_generator import generate_weekly_report
from backend.tools.workout_analyzer import analyze_workouts

Retriever = Callable[[str, int], list[dict]]


class FitLifeWorkflow:
    """The explicit FitLife workflow; safety seams become mandatory in phase 4."""

    def __init__(
        self,
        repository: FitnessRepository,
        gateway: ModelGateway,
        *,
        retriever: Retriever = retrieve_knowledge,
        context_metadata: dict | None = None,
    ) -> None:
        self.repository = repository
        self.gateway = gateway
        self.retriever = retriever
        self.context_metadata = dict(context_metadata or {})

    async def execute(self, command: AgentCommand, context: RuntimeContext) -> AgentResult:
        state: AgentState = {
            "operation": command.operation,
            "messages": [{"role": "user", "content": command.question}],
            "user_query": command.question,
            "current_user_id": command.user_id,
            "surface": command.surface,
            "context_date": command.context_date,
            "context_metadata": self.context_metadata,
            "tool_calls": list(command.initial_tool_calls),
            "tool_results": dict(command.initial_tool_results),
            "retrieved_docs": [],
        }
        await self._apply(context, "planner", state, self._planner)
        await self._apply(context, "profile_loader", state, self._profile_loader)
        await self._apply(context, "data_analyzer", state, self._data_analyzer)
        if _route(state).get("needs_retrieval"):
            await self._apply(context, "retriever", state, self._retriever)
        await self._apply(context, "deterministic_generator", state, self._generator)
        await self._apply(context, "deterministic_validator", state, self._validator)
        await self._apply(context, "writer", state, self._writer)
        # Phase 4 inserts input_guard before planner and safety_reviewer after writer.
        return await context.step("result_projector", lambda: self._project(state))

    async def _apply(self, context: RuntimeContext, name: str, state: AgentState, operation) -> None:
        state.update(await context.step(name, lambda: operation(state)))

    def _planner(self, state: AgentState) -> AgentState:
        route = _invoke_model(lambda: self.gateway.plan_route(state["user_query"]))
        return {"intent": route.intent, "tool_requests": route.model_dump(), "llm_used": True}

    def _profile_loader(self, state: AgentState) -> AgentState:
        return {
            "profile": self.repository.read_profile(state.get("current_user_id")).model_dump(),
            "tool_calls": _append_tool_call(state, "load_profile"),
        }

    def _data_analyzer(self, state: AgentState) -> AgentState:
        route = _route(state)
        profile = state["profile"]
        results = dict(state.get("tool_results", {}))
        calls = list(state.get("tool_calls", []))
        user_id = state.get("current_user_id")
        if "report_week" in results and "weekly_report" in results:
            return {"tool_calls": calls, "tool_results": results}
        if route.get("needs_meal_analysis"):
            calls = _append_tool_call({"tool_calls": calls}, "analyze_meals")
            results["meal_analysis"] = analyze_meals(
                self.repository.read_meals(user_id),
                calorie_target=profile["daily_calorie_target"],
                protein_target=profile["daily_protein_target"],
            )
        if route.get("needs_workout_analysis"):
            calls = _append_tool_call({"tool_calls": calls}, "analyze_workouts")
            results["workout_analysis"] = analyze_workouts(self.repository.read_workouts(user_id))
        return {"tool_calls": calls, "tool_results": results}

    def _retriever(self, state: AgentState) -> AgentState:
        route = _route(state)
        query = _build_retrieval_query(state["user_query"], route)
        docs = self.retriever(query, 4 if route.get("needs_report") else 3)
        return {
            "retrieval_query": query,
            "retrieved_docs": docs,
            "tool_calls": _append_tool_call(state, "retrieve_knowledge"),
        }

    def _generator(self, state: AgentState) -> AgentState:
        route = _route(state)
        profile = state["profile"]
        results = dict(state.get("tool_results", {}))
        calls = list(state.get("tool_calls", []))
        user_id = state.get("current_user_id")
        if route.get("needs_report") and "weekly_report" not in results:
            meal = results.get("meal_analysis")
            if meal is None:
                meal = analyze_meals(
                    self.repository.read_meals(user_id),
                    calorie_target=profile["daily_calorie_target"],
                    protein_target=profile["daily_protein_target"],
                )
                calls = _append_tool_call({"tool_calls": calls}, "analyze_meals")
            workout = results.get("workout_analysis")
            if workout is None:
                workout = analyze_workouts(self.repository.read_workouts(user_id))
                calls = _append_tool_call({"tool_calls": calls}, "analyze_workouts")
            results["weekly_report"] = generate_weekly_report(profile, meal, workout)
            calls = _append_tool_call({"tool_calls": calls}, "generate_weekly_report")
        if route.get("needs_plan") and "active_plan" not in results:
            results["generated_plan"] = generate_plan(profile)
            calls = _append_tool_call({"tool_calls": calls}, "generate_next_week_plan")
        return {"tool_calls": calls, "tool_results": results}

    def _validator(self, state: AgentState) -> AgentState:
        results = dict(state.get("tool_results", {}))
        validation = {"passed": True, "warnings": [], "violations": [], "repair_suggestions": []}
        calls = list(state.get("tool_calls", []))
        plan = results.get("generated_plan")
        if plan is not None:
            validation = validate_generated_plan(plan, state["profile"])
            results["generated_plan"] = {**plan, "validation": validation}
            calls = _append_tool_call({"tool_calls": calls}, "validate_plan")
        return {"tool_calls": calls, "tool_results": results, "validation_result": validation}

    def _writer(self, state: AgentState) -> AgentState:
        answer = _invoke_model(lambda: self.gateway.write_answer(state))
        if not answer.strip():
            raise model_gateway_error(ValueError("Model returned a blank answer"))
        return {"final_answer": answer, "llm_used": True, "llm_answer_used": True}

    def _project(self, state: AgentState) -> AgentResult:
        validation = state.get("validation_result") or {"passed": True, "warnings": []}
        docs = state.get("retrieved_docs", [])
        trace = {
            "intent": state.get("intent", ""),
            "tool_calls": state.get("tool_calls", []),
            "retrieved_sources": sorted({doc["source"] for doc in docs if "source" in doc}),
            "validation_passed": validation.get("passed", True),
            "warnings": validation.get("warnings", []),
            "llm_used": bool(state.get("llm_used", False)),
            "llm_answer_used": bool(state.get("llm_answer_used", False)),
        }
        return AgentResult(
            answer_markdown=state.get("final_answer", ""),
            intent=state.get("intent", ""),
            trace=trace,
            tool_results=state.get("tool_results", {}),
            sources=tuple(docs),
            model=self.gateway.model,
        )


def _invoke_model(operation):
    try:
        return operation()
    except ApplicationError:
        raise
    except Exception as error:
        raise model_gateway_error(error) from None


def _route(state: AgentState) -> dict:
    return state.get("tool_requests", {})


def _append_tool_call(state: dict, tool_name: str) -> list[str]:
    calls = list(state.get("tool_calls", []))
    if tool_name not in calls:
        calls.append(tool_name)
    return calls


def _build_retrieval_query(question: str, route: dict) -> str:
    if route.get("needs_report"):
        return f"{question} nutrition_guidelines nutrition_guidelines nutrition guidelines calories protein"
    if route.get("needs_plan"):
        return f"{question} plan workout training diet rest meal fitness"
    return question
