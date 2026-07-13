from backend.agent.planner import PlannerRoute
from backend.application.ports.model_gateway import ModelGateway


class FakeGateway:
    model = "fake-model"

    def plan_route(self, question: str) -> PlannerRoute:
        return PlannerRoute(intent="knowledge_qa", needs_retrieval=True)

    def write_answer(self, state: dict) -> str:
        return "answer"


def test_model_gateway_protocol_accepts_compatible_adapter():
    gateway = FakeGateway()

    assert isinstance(gateway, ModelGateway)
    assert gateway.write_answer({"user_query": "hello"}) == "answer"
