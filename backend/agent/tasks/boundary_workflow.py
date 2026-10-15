"""Fixed product-boundary responses with the same mandatory safety seams."""
from backend.agent.contracts import AgentResult
from backend.agent.safety import check_input, review_output
from backend.agent.workflow import verify_guard_steps
from backend.safety.context import sanitize_context
from backend.safety.gate import default_pack


class BoundaryWorkflow:
    def __init__(self, decision):
        self.decision = decision

    async def execute(self, command, context):
        await context.step("input_guard", lambda: check_input(command.question))
        await context.step("context_guard", lambda: sanitize_context({}, default_pack()))
        answer = ("你好！我可以帮助你了解 FitLife，以及健身、训练和饮食问题。"
                  if self.decision.scope == "in_scope" else
                  "请单独说明你希望获得的健身、训练或饮食帮助。"
                  if self.decision.needs_clarification else
                  "我可以帮助你处理健身、训练、饮食和 FitLife 使用问题，无法提供选股或其他无关服务。")
        answer, _ = await context.step("safety_reviewer", lambda: review_output(command.question, answer))
        verify_guard_steps(self, tuple(context.completed_steps))
        return AgentResult(answer, "business_scope", {
            "scope": self.decision.scope, "refusal_code": self.decision.refusal_code,
            "needs_clarification": self.decision.needs_clarification,
            "tool_calls": [], "llm_used": False, "llm_answer_used": False,
        }, {}, (), "")
