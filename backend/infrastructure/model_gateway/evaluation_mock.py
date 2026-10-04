"""Explicit offline evaluation adapter; never a live error fallback."""
from backend.agent.planner import plan_route
from backend.agent.writer import write_answer


class EvaluationMockGateway:
    provider = "mock"
    model = "deterministic-eval-v1"

    def plan_route(self, question):
        return plan_route(question)

    def write_answer(self, state):
        return write_answer(state)
