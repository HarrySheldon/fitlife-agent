from __future__ import annotations

from datetime import date as date_type
from uuid import uuid4

from backend.agent.generator import generate_plan
from backend.agent.state import AgentState
from backend.agent.validator import validate_generated_plan
from backend.application.ports.fitness_repository import FitnessRepository
from backend.application.ports.model_gateway import ModelGateway
from backend.application.use_cases.generate_plan import GeneratePlan
from backend.application.use_cases.generate_weekly_report import GenerateWeeklyReport
from backend.domain.errors import ApplicationError, ai_not_configured_error, model_gateway_error
from backend.infrastructure.model_gateway.openai_responses import build_model_gateway
from backend.infrastructure.repositories.file_fitness_repository import FileFitnessRepository
from backend.rag.retriever import retrieve_knowledge
from backend.tools.meal_analyzer import analyze_meals
from backend.tools.report_generator import generate_weekly_report
from backend.tools.target_suggestions import suggest_targets
from backend.tools.today_overview import build_today_overview_from_records
from backend.tools.workout_analyzer import analyze_workouts


def run_fitlife_agent(
    question: str,
    user_id: str | None = None,
    *,
    repository: FitnessRepository | None = None,
    gateway: ModelGateway | None = None,
    initial_tool_results: dict | None = None,
    initial_tool_calls: list[str] | None = None,
) -> dict:
    repository = repository or FileFitnessRepository()
    if gateway is None:
        try:
            gateway = build_model_gateway()
        except ApplicationError:
            raise
        except Exception as error:
            raise model_gateway_error(error) from None
    if gateway is None:
        raise ai_not_configured_error()

    graph = build_graph(repository=repository, gateway=gateway)
    state = graph.invoke(
        {
            "messages": [{"role": "user", "content": question}],
            "user_query": question,
            "current_user_id": user_id,
            "tool_calls": list(initial_tool_calls or []),
            "tool_results": dict(initial_tool_results or {}),
            "retrieved_docs": [],
        }
    )
    return _format_agent_result(state, model=gateway.model)


def run_contextual_coach_action(
    surface: str,
    action: str,
    date: str | None,
    question: str | None = None,
    user_id: str | None = None,
    *,
    repository: FitnessRepository | None = None,
    gateway: ModelGateway | None = None,
) -> dict:
    repository = repository or FileFitnessRepository()
    prompt = _coach_prompt(surface, action, date, question)
    tool_results, tool_calls = _build_contextual_tool_context(
        action,
        date,
        user_id,
        repository,
    )
    result = run_fitlife_agent(
        prompt,
        user_id,
        repository=repository,
        gateway=gateway,
        initial_tool_results=tool_results,
        initial_tool_calls=tool_calls,
    )
    result["trace"] = {
        **result.get("trace", {}),
        "surface": surface,
        "coach_action": action,
        "context_date": date,
    }
    return result


def _build_contextual_tool_context(
    action: str,
    date: str | None,
    user_id: str | None,
    repository: FitnessRepository,
) -> tuple[dict, list[str]]:
    if action == "suggest_targets":
        suggestion = suggest_targets(repository.read_profile(user_id))
        return {"target_suggestion": suggestion.model_dump()}, ["suggest_targets"]

    if action == "explain_weekly_report":
        report = GenerateWeeklyReport(repository).execute(user_id)
        return {"weekly_report": report}, list(report["trace"]["tool_calls"])

    if action == "adjust_next_plan":
        plan = GeneratePlan(repository).execute(user_id)
        return {"generated_plan": plan}, list(plan["trace"]["tool_calls"])

    day = date or date_type.today().isoformat()
    overview = build_today_overview_from_records(
        day,
        repository.read_profile(user_id),
        repository.read_meals(user_id),
        repository.read_workouts(user_id),
    )
    return {"today_overview": overview.model_dump()}, ["build_today_overview"]


def _coach_prompt(surface: str, action: str, date: str | None, question: str | None) -> str:
    base = {
        "explain_today": "Explain today's calorie, protein, and training status using the user's records.",
        "suggest_next_meal": "Suggest the next meal using today's remaining calorie and protein gap.",
        "adjust_today_training": "Suggest a practical training adjustment for today based on the user's profile and records.",
        "explain_weekly_report": "Create a weekly summary report, then explain the most important behavior change.",
        "adjust_next_plan": "Create a plan for next week and adjust it using recent records and the user's profile.",
        "suggest_targets": "Suggest calorie and protein targets from the user's body state, goal, and training frequency.",
    }[action]
    suffix = f" Date: {date}." if date else ""
    user_text = f" User question: {question}" if question else ""
    return f"{base} Surface: {surface}.{suffix}{user_text}"


def build_graph(
    *,
    repository: FitnessRepository,
    gateway: ModelGateway,
):
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(AgentState)
    builder.add_node("planner", lambda state: planner_node(state, gateway))
    builder.add_node("profile_loader", lambda state: profile_loader_node(state, repository))
    builder.add_node("data_analyzer", lambda state: data_analyzer_node(state, repository))
    builder.add_node("retriever", retriever_node)
    builder.add_node("generator", lambda state: generator_node(state, repository))
    builder.add_node("validator", validator_node)
    builder.add_node("writer", lambda state: writer_node(state, gateway))
    builder.add_node("trace_builder", trace_builder_node)
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "profile_loader")
    builder.add_edge("profile_loader", "data_analyzer")
    builder.add_conditional_edges(
        "data_analyzer",
        route_after_analysis,
        {"retriever": "retriever", "generator": "generator"},
    )
    builder.add_edge("retriever", "generator")
    builder.add_edge("generator", "validator")
    builder.add_edge("validator", "writer")
    builder.add_edge("writer", "trace_builder")
    builder.add_edge("trace_builder", END)
    return builder.compile()


def planner_node(state: AgentState, gateway: ModelGateway) -> AgentState:
    route = _invoke_model(lambda: gateway.plan_route(state["user_query"]))
    return {
        "intent": route.intent,
        "tool_requests": route.model_dump(),
        "llm_used": True,
    }


def profile_loader_node(state: AgentState, repository: FitnessRepository) -> AgentState:
    return {
        "profile": repository.read_profile(state.get("current_user_id")).model_dump(),
        "tool_calls": _append_tool_call(state, "load_profile"),
    }


def data_analyzer_node(state: AgentState, repository: FitnessRepository) -> AgentState:
    route = _route(state)
    profile = state["profile"]
    tool_results = dict(state.get("tool_results", {}))
    tool_calls = list(state.get("tool_calls", []))
    user_id = state.get("current_user_id")

    if route.get("needs_meal_analysis"):
        tool_calls = _append_tool_call({"tool_calls": tool_calls}, "analyze_meals")
        tool_results["meal_analysis"] = analyze_meals(
            repository.read_meals(user_id),
            calorie_target=profile["daily_calorie_target"],
            protein_target=profile["daily_protein_target"],
        )
    if route.get("needs_workout_analysis"):
        tool_calls = _append_tool_call({"tool_calls": tool_calls}, "analyze_workouts")
        tool_results["workout_analysis"] = analyze_workouts(repository.read_workouts(user_id))

    return {"tool_calls": tool_calls, "tool_results": tool_results}


def route_after_analysis(state: AgentState) -> str:
    return "retriever" if _route(state).get("needs_retrieval") else "generator"


def retriever_node(state: AgentState) -> AgentState:
    route = _route(state)
    retrieval_query = _build_retrieval_query(state["user_query"], route)
    retrieved_docs = retrieve_knowledge(retrieval_query, top_k=4 if route.get("needs_report") else 3)
    return {
        "retrieval_query": retrieval_query,
        "retrieved_docs": retrieved_docs,
        "tool_calls": _append_tool_call(state, "retrieve_knowledge"),
    }


def generator_node(state: AgentState, repository: FitnessRepository) -> AgentState:
    route = _route(state)
    profile = state["profile"]
    tool_results = dict(state.get("tool_results", {}))
    tool_calls = list(state.get("tool_calls", []))
    user_id = state.get("current_user_id")

    if route.get("needs_report"):
        meal_result = tool_results.get("meal_analysis")
        if meal_result is None:
            meal_result = analyze_meals(
                repository.read_meals(user_id),
                calorie_target=profile["daily_calorie_target"],
                protein_target=profile["daily_protein_target"],
            )
            tool_calls = _append_tool_call({"tool_calls": tool_calls}, "analyze_meals")

        workout_result = tool_results.get("workout_analysis")
        if workout_result is None:
            workout_result = analyze_workouts(repository.read_workouts(user_id))
            tool_calls = _append_tool_call({"tool_calls": tool_calls}, "analyze_workouts")

        tool_results["weekly_report"] = generate_weekly_report(profile, meal_result, workout_result)
        tool_calls = _append_tool_call({"tool_calls": tool_calls}, "generate_weekly_report")

    if route.get("needs_plan"):
        tool_results["generated_plan"] = generate_plan(profile)
        tool_calls = _append_tool_call({"tool_calls": tool_calls}, "generate_next_week_plan")

    return {"tool_calls": tool_calls, "tool_results": tool_results}


def validator_node(state: AgentState) -> AgentState:
    tool_results = dict(state.get("tool_results", {}))
    validation = {"passed": True, "warnings": [], "violations": [], "repair_suggestions": []}
    tool_calls = list(state.get("tool_calls", []))

    generated_plan = tool_results.get("generated_plan")
    if generated_plan is not None:
        validation = validate_generated_plan(generated_plan, state["profile"])
        tool_results["generated_plan"] = {**generated_plan, "validation": validation}
        tool_calls = _append_tool_call({"tool_calls": tool_calls}, "validate_plan")

    return {
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "validation_result": validation,
    }


def writer_node(state: AgentState, gateway: ModelGateway) -> AgentState:
    answer = _invoke_model(lambda: gateway.write_answer(state))
    if not answer.strip():
        raise model_gateway_error(ValueError("Model returned a blank answer"))
    return {"final_answer": answer, "llm_used": True, "llm_answer_used": True}


def trace_builder_node(state: AgentState) -> AgentState:
    validation = state.get("validation_result") or {"passed": True, "warnings": []}
    retrieved_docs = state.get("retrieved_docs", [])
    trace = {
        "intent": state.get("intent", ""),
        "tool_calls": state.get("tool_calls", []),
        "retrieved_sources": sorted({doc["source"] for doc in retrieved_docs if "source" in doc}),
        "validation_passed": validation.get("passed", True),
        "warnings": validation.get("warnings", []),
        "llm_used": bool(state.get("llm_used", False)),
        "llm_answer_used": bool(state.get("llm_answer_used", False)),
    }
    return {"trace": trace}


def _invoke_model(operation):
    try:
        return operation()
    except ApplicationError:
        raise
    except Exception as error:
        raise model_gateway_error(error) from None


def _format_agent_result(state: dict, *, model: str) -> dict:
    return {
        "answer_markdown": state.get("final_answer", ""),
        "intent": state.get("intent", ""),
        "trace": state.get("trace", {}),
        "tool_results": state.get("tool_results", {}),
        "sources": state.get("retrieved_docs", []),
        "model": model,
        "request_id": uuid4().hex,
    }


def _route(state: AgentState) -> dict:
    return state.get("tool_requests", {})


def _append_tool_call(state: dict, tool_name: str) -> list[str]:
    tool_calls = list(state.get("tool_calls", []))
    if tool_name not in tool_calls:
        tool_calls.append(tool_name)
    return tool_calls


def _build_retrieval_query(question: str, route: dict) -> str:
    if route.get("needs_report"):
        return f"{question} nutrition_guidelines nutrition_guidelines nutrition guidelines calories protein"
    if route.get("needs_plan"):
        return f"{question} plan workout training diet rest meal fitness"
    return question
