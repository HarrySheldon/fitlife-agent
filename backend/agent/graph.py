from __future__ import annotations

from backend.agent.generator import generate_plan
from backend.agent.llm_adapter import try_plan_route_with_llm, try_write_answer_with_llm
from backend.agent.planner import plan_route
from backend.agent.state import AgentState
from backend.agent.validator import validate_generated_plan
from backend.agent.writer import write_answer
from backend.rag.retriever import retrieve_knowledge
from backend.tools.data_access import read_meals, read_profile, read_workouts
from backend.tools.meal_analyzer import analyze_meals
from backend.tools.report_generator import generate_weekly_report
from backend.tools.workout_analyzer import analyze_workouts


def run_fitlife_agent(question: str, user_id: str | None = None) -> dict:
    graph = build_graph()
    if graph is None:
        raise RuntimeError("LangGraph workflow could not be built")

    state = graph.invoke(
        {
            "messages": [{"role": "user", "content": question}],
            "user_query": question,
            "current_user_id": user_id,
            "tool_calls": [],
            "tool_results": {},
            "retrieved_docs": [],
        }
    )
    return _format_agent_result(state)


def planner_node(state: AgentState) -> AgentState:
    llm_route = try_plan_route_with_llm(state["user_query"])
    route = llm_route or plan_route(state["user_query"])
    update: AgentState = {"intent": route.intent, "tool_requests": route.model_dump()}
    if llm_route is not None:
        update["llm_used"] = True
    return update


def build_graph():
    try:
        from langgraph.graph import END, START, StateGraph

        builder = StateGraph(AgentState)
        builder.add_node("planner", planner_node)
        builder.add_node("profile_loader", profile_loader_node)
        builder.add_node("data_analyzer", data_analyzer_node)
        builder.add_node("retriever", retriever_node)
        builder.add_node("generator", generator_node)
        builder.add_node("validator", validator_node)
        builder.add_node("writer", writer_node)
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
    except Exception:
        return None


def profile_loader_node(state: AgentState) -> AgentState:
    return {
        "profile": read_profile(state.get("current_user_id")).model_dump(),
        "tool_calls": _append_tool_call(state, "load_profile"),
    }


def data_analyzer_node(state: AgentState) -> AgentState:
    route = _route(state)
    profile = state["profile"]
    tool_results = dict(state.get("tool_results", {}))
    tool_calls = list(state.get("tool_calls", []))

    if route.get("needs_meal_analysis"):
        tool_calls = _append_tool_call({"tool_calls": tool_calls}, "analyze_meals")
        tool_results["meal_analysis"] = analyze_meals(
            read_meals(state.get("current_user_id")),
            calorie_target=profile["daily_calorie_target"],
            protein_target=profile["daily_protein_target"],
        )
    if route.get("needs_workout_analysis"):
        tool_calls = _append_tool_call({"tool_calls": tool_calls}, "analyze_workouts")
        tool_results["workout_analysis"] = analyze_workouts(read_workouts(state.get("current_user_id")))

    return {"tool_calls": tool_calls, "tool_results": tool_results}


def route_after_analysis(state: AgentState) -> str:
    if _route(state).get("needs_retrieval"):
        return "retriever"
    return "generator"


def retriever_node(state: AgentState) -> AgentState:
    route = _route(state)
    retrieval_query = _build_retrieval_query(state["user_query"], route)
    retrieved_docs = retrieve_knowledge(retrieval_query, top_k=4 if route.get("needs_report") else 3)
    return {
        "retrieval_query": retrieval_query,
        "retrieved_docs": retrieved_docs,
        "tool_calls": _append_tool_call(state, "retrieve_knowledge"),
    }


def generator_node(state: AgentState) -> AgentState:
    route = _route(state)
    profile = state["profile"]
    tool_results = dict(state.get("tool_results", {}))
    tool_calls = list(state.get("tool_calls", []))

    if route.get("needs_report"):
        meal_result = tool_results.get("meal_analysis")
        if meal_result is None:
            meal_result = analyze_meals(
                read_meals(state.get("current_user_id")),
                calorie_target=profile["daily_calorie_target"],
                protein_target=profile["daily_protein_target"],
            )
            tool_calls = _append_tool_call({"tool_calls": tool_calls}, "analyze_meals")

        workout_result = tool_results.get("workout_analysis")
        if workout_result is None:
            workout_result = analyze_workouts(read_workouts(state.get("current_user_id")))
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


def writer_node(state: AgentState) -> AgentState:
    llm_answer = try_write_answer_with_llm(state)
    if llm_answer:
        return {"final_answer": llm_answer, "llm_used": True}
    return {"final_answer": write_answer(state)}


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
    }
    return {"trace": trace}


def _format_agent_result(state: dict) -> dict:
    return {
        "answer_markdown": state.get("final_answer", ""),
        "intent": state.get("intent", ""),
        "trace": state.get("trace", {}),
        "tool_results": state.get("tool_results", {}),
        "sources": state.get("retrieved_docs", []),
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
