from __future__ import annotations

from datetime import date as date_type

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
from backend.tools.target_suggestions import suggest_targets
from backend.tools.today_overview import build_today_overview
from backend.tools.workout_analyzer import analyze_workouts


DETERMINISTIC_CONTEXT_ACTIONS = {
    "explain_today",
    "suggest_next_meal",
    "adjust_today_training",
    "suggest_targets",
}


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


def run_contextual_coach_action(
    surface: str,
    action: str,
    date: str | None,
    question: str | None = None,
    user_id: str | None = None,
) -> dict:
    prompt = _coach_prompt(surface, action, date, question)
    result = run_fitlife_agent(prompt, user_id)
    trace = dict(result.get("trace", {}))
    if action in DETERMINISTIC_CONTEXT_ACTIONS or not trace.get("llm_answer_used", False):
        answer, context_tools = _deterministic_coach_answer(action, date, user_id, result)
        result["answer_markdown"] = answer
        tool_calls = list(trace.get("tool_calls", []))
        for tool_name in context_tools:
            if tool_name not in tool_calls:
                tool_calls.append(tool_name)
        trace["tool_calls"] = tool_calls
    result["trace"] = {
        **trace,
        "surface": surface,
        "coach_action": action,
        "context_date": date,
    }
    return result


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


def _deterministic_coach_answer(
    action: str,
    date: str | None,
    user_id: str | None,
    result: dict,
) -> tuple[str, list[str]]:
    if action == "suggest_targets":
        suggestion = suggest_targets(read_profile(user_id))
        return (
            "\n".join(
                [
                    "## Suggested targets",
                    f"- Daily calories: {suggestion.daily_calorie_target} kcal",
                    f"- Daily protein: {suggestion.daily_protein_target} g",
                    f"- Rationale: {suggestion.rationale}",
                ]
            ),
            ["suggest_targets"],
        )

    if action == "explain_weekly_report":
        report = result.get("tool_results", {}).get("weekly_report", {})
        sections = "\n".join(
            f"### {item['title']}\n{item['content']}" for item in report.get("sections", [])
        )
        checklist = "\n".join(f"- {item}" for item in report.get("checklist", []))
        if sections or checklist:
            return f"## Weekly review\n{sections}\n\n### Next actions\n{checklist}", []
        return result.get("answer_markdown", ""), []

    if action == "adjust_next_plan":
        plan = result.get("tool_results", {}).get("generated_plan", {})
        diet = plan.get("diet_plan", {})
        validation = plan.get("validation", {})
        findings = validation.get("warnings", []) + validation.get("violations", [])
        finding_text = "\n".join(f"- {item}" for item in findings) or "- No blocking validation findings."
        if plan:
            return (
                "\n".join(
                    [
                        "## Adjusted next plan",
                        f"- Daily calories: {diet.get('daily_calorie_target')} kcal",
                        f"- Daily protein: {diet.get('daily_protein_target')} g",
                        "### Validation",
                        finding_text,
                    ]
                ),
                [],
            )
        return result.get("answer_markdown", ""), []

    day = date or date_type.today().isoformat()
    overview = build_today_overview(day, user_id)
    targets = {target.label: target for target in overview.targets}
    calories = targets["Calories"]
    protein = targets["Protein"]

    if action == "explain_today":
        return (
            "\n".join(
                [
                    f"## Today's status — {day}",
                    f"- Calories: {calories.current:.0f} / {calories.target:.0f} kcal",
                    f"- Protein: {protein.current:.0f} / {protein.target:.0f} g",
                    f"- Meals recorded: {overview.summary.meal_count}",
                    f"- Training sessions: {overview.summary.training_sessions}",
                ]
            ),
            ["build_today_overview"],
        )

    if action == "suggest_next_meal":
        calorie_gap = max(0, calories.remaining)
        protein_gap = max(0, protein.remaining)
        if calorie_gap == 0 and protein_gap == 0:
            suggestion = "Daily calorie and protein targets are already met; choose a light meal only if hungry."
        elif protein_gap >= 30:
            suggestion = "Prioritize a lean protein serving with vegetables and a moderate carbohydrate portion."
        else:
            suggestion = "Choose a balanced meal with one protein serving and adjust the portion to the calorie gap."
        return (
            "\n".join(
                [
                    f"## Next meal — {day}",
                    f"- Remaining: {calorie_gap:.0f} kcal and {protein_gap:.0f} g protein",
                    f"- Suggestion: {suggestion}",
                ]
            ),
            ["build_today_overview"],
        )

    profile = read_profile(user_id)
    if overview.summary.training_sessions > 0:
        training_text = "A session is already recorded. Keep the next block light and prioritize recovery."
    else:
        training_text = (
            f"No session is recorded. Schedule one practical {profile.training_preference} session "
            f"that fits your {profile.weekly_training_frequency}-day weekly target."
        )
    return (
        f"## Training adjustment — {day}\n- {training_text}",
        ["build_today_overview", "load_profile"],
    )


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
        return {"final_answer": llm_answer, "llm_used": True, "llm_answer_used": True}
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
        "llm_answer_used": bool(state.get("llm_answer_used", False)),
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
