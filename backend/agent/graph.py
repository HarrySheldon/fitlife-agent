from __future__ import annotations

from backend.agent.generator import generate_plan
from backend.agent.planner import plan_route
from backend.agent.writer import write_answer
from backend.rag.retriever import retrieve_knowledge
from backend.tools.data_access import read_meals, read_profile, read_workouts
from backend.tools.meal_analyzer import analyze_meals
from backend.tools.report_generator import generate_weekly_report
from backend.tools.workout_analyzer import analyze_workouts


def run_fitlife_agent(question: str) -> dict:
    route = plan_route(question)
    profile = read_profile().model_dump()
    tool_calls = ["load_profile"]
    tool_results: dict = {}
    retrieved_docs: list[dict] = []

    if route.needs_meal_analysis:
        tool_calls.append("analyze_meals")
        tool_results["meal_analysis"] = analyze_meals(
            read_meals(),
            calorie_target=profile["daily_calorie_target"],
            protein_target=profile["daily_protein_target"],
        )
    if route.needs_workout_analysis:
        tool_calls.append("analyze_workouts")
        tool_results["workout_analysis"] = analyze_workouts(read_workouts())
    if route.needs_retrieval:
        tool_calls.append("retrieve_knowledge")
        retrieval_query = question
        if route.needs_report:
            retrieval_query = f"{question} 饮食 热量 蛋白质 nutrition"
        elif route.needs_plan:
            retrieval_query = f"{question} 计划 训练 饮食 休息"
        retrieved_docs = retrieve_knowledge(retrieval_query, top_k=4 if route.needs_report else 3)
    if route.needs_report:
        tool_calls.append("generate_weekly_report")
        meal_result = tool_results.get("meal_analysis") or analyze_meals(
            read_meals(), profile["daily_calorie_target"], profile["daily_protein_target"]
        )
        workout_result = tool_results.get("workout_analysis") or analyze_workouts(read_workouts())
        tool_results["weekly_report"] = generate_weekly_report(profile, meal_result, workout_result)
    if route.needs_plan:
        tool_calls.append("generate_next_week_plan")
        tool_calls.append("validate_plan")
        tool_results["generated_plan"] = generate_plan(profile)

    state = {
        "user_query": question,
        "intent": route.intent,
        "profile": profile,
        "tool_results": tool_results,
        "retrieved_docs": retrieved_docs,
    }
    answer = write_answer(state)
    validation = (tool_results.get("generated_plan") or {}).get("validation", {"passed": True})
    trace = {
        "intent": route.intent,
        "tool_calls": tool_calls,
        "retrieved_sources": sorted({doc["source"] for doc in retrieved_docs}),
        "validation_passed": validation.get("passed", True),
        "warnings": validation.get("warnings", []),
    }
    return {
        "answer_markdown": answer,
        "intent": route.intent,
        "trace": trace,
        "tool_results": tool_results,
        "sources": retrieved_docs,
    }


def build_graph():
    try:
        from langgraph.graph import END, START, StateGraph

        from backend.agent.state import AgentState

        def planner_node(state: AgentState) -> AgentState:
            route = plan_route(state["user_query"])
            return {"intent": route.intent, "tool_requests": route.model_dump()}

        builder = StateGraph(AgentState)
        builder.add_node("planner", planner_node)
        builder.add_edge(START, "planner")
        builder.add_edge("planner", END)
        return builder.compile()
    except Exception:
        return None
