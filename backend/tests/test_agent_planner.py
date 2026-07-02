from backend.agent.planner import plan_route


def test_planner_routes_meal_question_to_meal_analysis():
    route = plan_route("我这周蛋白质吃够了吗？")

    assert route.intent == "meal_analysis"
    assert route.needs_meal_analysis is True
    assert route.needs_workout_analysis is False


def test_planner_routes_plan_question_to_plan_generation_and_retrieval():
    route = plan_route("我想减脂，下周怎么安排训练？")

    assert route.intent == "plan_generation"
    assert route.needs_plan is True
    assert route.needs_retrieval is True


def test_planner_routes_replacement_question_to_knowledge_qa():
    route = plan_route("我不想吃鸡胸肉，有什么替代？")

    assert route.intent == "knowledge_qa"
    assert route.needs_retrieval is True
