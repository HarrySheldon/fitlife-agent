"""Use the existing structured gateway, including its local JSON fallback."""
import json
from copy import copy
from backend.agent.decision import DecisionEnvelope
from backend.application.ports.agent_decision_gateway import AgentDecisionResult
from backend.application.ports.model_call_context import model_output_limit


class StructuredDecisionAdapter:
    def __init__(self, gateway):
        # Dynamic argument maps are locally validated. Do not require a provider
        # to accept that open JSON map as its native strict response schema, and
        # never mutate the shared saved connection to switch generation modes.
        self.gateway = copy(gateway) if hasattr(gateway, 'structured_mode') else gateway
        if hasattr(self.gateway, 'structured_mode'):
            self.gateway.structured_mode = 'json'
        self.model = gateway.model
        self.provider = getattr(gateway, 'provider', None)

    def decide(self, request):
        token = model_output_limit.set(request.max_output_tokens)
        try:
            result = self.gateway.parse_structured(
                instructions=request.instructions,
                input_text=json.dumps({'tools': request.tool_descriptions,
                                       'messages': request.messages}, ensure_ascii=False),
                response_model=DecisionEnvelope,
            )
            envelope = DecisionEnvelope.model_validate(result.output.model_dump())
            return AgentDecisionResult(envelope.decision, result.model, result.usage)
        finally:
            model_output_limit.reset(token)
