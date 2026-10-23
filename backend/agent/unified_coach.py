"""One bounded decision maker. Domain operations live behind deterministic tools."""
from dataclasses import replace
import json
from pydantic import ValidationError
from backend.agent.context_builder import build_context, serialized
from backend.agent.coach_delivery import review_delivery, answer_contract
from backend.agent.contracts import AgentResult
from backend.agent.decision import ToolCall, DecisionEnvelope
from backend.agent.runtime import BudgetExceeded
from backend.agent.safety import check_input
from backend.agent.tools.registry import tool_descriptions
from backend.agent.skills.catalog import SkillResourceError
from backend.agent.workflow import verify_guard_steps
from backend.safety.context import sanitize_context
from backend.safety.gate import default_pack
from backend.domain.coach_answer import limits_for_or_default, output_token_limit


class UnifiedCoachWorkflow:
    def __init__(self, gateway, executor, *, review_gateway=None, review_mode='off'):
        self.gateway, self.executor = gateway, executor
        self.review_gateway, self.review_mode = review_gateway, review_mode

    async def execute(self, command, context):
        await context.step('input_guard', lambda: check_input(command.question))
        principal = self.executor.principal
        if command.user_id != principal.owner_id:
            raise PermissionError('OWNER_MISMATCH')
        request = build_context(principal, command, tool_descriptions())
        context.set_model_metadata(provider=getattr(self.gateway, 'provider', None), model=self.gateway.model)
        failures = protocol_failures = 0
        for decision_index in range(1, 13):
            context.raise_if_cancelled()
            self.executor.check_access()
            context.consume_context(request.instructions + serialized(request.tool_descriptions) + serialized(request.messages))
            action = command.coach_action
            if not action and 'training' in self.executor.principal.authorized_domains:
                action = 'training_plan_advice'
            remaining = context.policy.budget.max_tokens - context.tokens - context.output_tokens
            if remaining <= 0:
                raise BudgetExceeded('Agent output budget exhausted')
            request = replace(request, max_output_tokens=min(remaining,
                output_token_limit(limits_for_or_default(action, command.answer_mode or 'brief'))))
            def progress():
                context.record('AGENT_PROGRESS', context, {
                    'decision_count': decision_index, 'protocol_failures': protocol_failures,
                    'context_chars': len(request.instructions + serialized(request.tool_descriptions) + serialized(request.messages)),
                    'loaded_skill_ids': sorted({item['data']['resource_id'] for item in self.executor.observations.values()
                        if item['tool'] == 'resources.read' and item['status'] == 'ok'}),
                })
            progress()
            try:
                def decide():
                    # Recheck after Runtime's worker queue, immediately before
                    # forwarding already-read private observations to a provider.
                    self.executor.check_access()
                    return self.gateway.decide(request)
                response = await context.tool('agent_decision_model', 'safe', decide)
                decision = DecisionEnvelope.model_validate({'decision': response.decision}).decision
                context.consume_output(DecisionEnvelope(decision=decision).model_dump_json())
            except (ValidationError, ValueError) as error:
                if isinstance(error, SkillResourceError):
                    raise
                protocol_failures += 1
                progress()
                failures += 1
                if failures >= 2:
                    raise ValueError('AGENT_PROTOCOL_FAILED') from None
                request = replace(request, messages=(*request.messages, {
                    'role': 'user', 'source': 'protocol_error', 'content': 'INVALID_DECISION_SCHEMA'}))
                continue
            if isinstance(decision, ToolCall):
                observation = await self.executor.execute(principal, decision, context)
                failures = failures + 1 if observation['status'] != 'ok' else 0
                if failures >= 2:
                    raise ValueError('AGENT_ACTION_FAILED')
                # Published Skills are workflow instructions of lower authority.
                # User records/knowledge are data, sanitized at each model ingress.
                payload = observation
                if observation['tool'] not in {'skills.search', 'resources.read'}:
                    payload, _ = await context.step('context_guard', lambda: sanitize_context(
                        observation, default_pack(), scan_all=True))
                else:
                    await context.step('context_guard', lambda: None)
                request = replace(request, messages=(*request.messages,
                    {'role': 'assistant', 'content': decision.model_dump_json(), 'source': 'agent_action'},
                    {'role': 'user', 'content': serialized(payload), 'source': 'tool_data',
                     'revision': decision_index}))
                continue
            await context.step('context_guard', lambda: None)
            answer, verdict = await context.step('safety_reviewer', lambda: review_delivery(
                decision, self.executor, command, context, gateway=self.review_gateway, mode=self.review_mode))
            verify_guard_steps(self, tuple(context.completed_steps))
            context.raise_if_cancelled()
            refs = getattr(decision, 'evidence_refs', [])
            sources = []
            for reference in refs:
                observation = self.executor.evidence(reference)
                if observation['tool'] == 'knowledge.search':
                    sources.extend({'source': item.get('source', ''), 'heading': item.get('heading', '')}
                                   for item in observation['data'])
            return AgentResult(answer, 'coach_advice', {
                'scope': 'in_scope', 'llm_used': True, 'llm_answer_used': True,
                'agent_mode': 'unified', 'answer_contract': answer_contract(decision, self.executor, command),
                'answer_language': command.language or 'en-US', 'answer_mode': command.answer_mode or 'brief',
                'decision_count': decision_index, 'tool_attempts': self.executor.attempts,
                'tool_executions': self.executor.executions, 'tool_denials': self.executor.denials,
                'cache_hits': self.executor.cache_hits, 'protocol_failures': protocol_failures,
                'tool_calls': list(context.completed_tools), 'safety_outcome': verdict.outcome,
                'review_mode': self.review_mode,
                'loaded_skill_ids': sorted({item['data']['resource_id'] for item in self.executor.observations.values()
                    if item['tool'] == 'resources.read' and item['status'] == 'ok'}),
            }, {}, tuple(sources), self.gateway.model)
        raise BudgetExceeded('Agent decision budget exhausted')
