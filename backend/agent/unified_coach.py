"""One bounded decision maker. Domain operations live behind deterministic tools."""
from dataclasses import replace
import json
from pydantic import ValidationError
from backend.agent.context_builder import build_context, serialized
from backend.agent.context_policy import ContextPolicyConfig, organize_rear
from backend.agent.coach_delivery import review_delivery, answer_contract
from backend.agent.contracts import AgentResult
from backend.agent.decision import ToolCall, DecisionEnvelope
from backend.agent.runtime import BudgetExceeded
from backend.agent.safety import check_input
from backend.agent.tools.registry import tool_descriptions
from backend.agent.skills.catalog import SkillResourceError
from backend.agent.task_session import AdviceSession
from backend.agent.workflow import verify_guard_steps
from backend.safety.context import sanitize_context
from backend.safety.gate import default_pack
from backend.domain.coach_answer import limits_for_or_default, output_token_limit


class UnifiedCoachWorkflow:
    def __init__(self, gateway, executor, *, review_gateway=None, review_mode='off', session=None,
                 context_policy=None):
        self.gateway, self.executor = gateway, executor
        self.review_gateway, self.review_mode = review_gateway, review_mode
        # Plain advice is the default: no task, no rounds, no receipt.
        self.session = session or AdviceSession()
        # Reference is the default: it is the baseline the optimisation is
        # measured against, so a caller has to choose the other side explicitly.
        self.context_policy = context_policy or ContextPolicyConfig()

    async def _prefetch(self, principal, plan, request, context):
        """Attach published resources the trusted action is known to need.

        A resource that cannot be read is not substituted: the run simply falls
        back to discovering it, which is what it did before this existed.
        """
        added = []
        for resource_id in plan.resource_ids:
            observation = await self.executor.prefetch(principal, resource_id, context)
            if observation.get('status') != 'ok':
                continue
            added.append({'role': 'user', 'source': 'prefetched_resource',
                          'content': serialized(observation), 'call_id': observation['call_id'],
                          'tool': observation['tool'], 'status': 'ok',
                          'source_version': observation.get('source_version'),
                          'required_domains': list(observation.get('required_domains') or [])})
        if not added:
            return request
        # Placed after the history and before the current request, so the stable
        # prefix, the question and the runtime frame keep their positions.
        cut = next((index for index in range(len(request.messages) - 1, -1, -1)
                    if request.messages[index].get('source') == 'current_request'),
                   len(request.messages))
        return replace(request, messages=(*request.messages[:cut], *added, *request.messages[cut:]))

    async def execute(self, command, context):
        await context.step('input_guard', lambda: check_input(command.question))
        principal = self.executor.principal
        if command.user_id != principal.owner_id:
            raise PermissionError('OWNER_MISMATCH')
        policy = self.context_policy
        plan = policy.plan_for(command)
        request = build_context(principal, command, tool_descriptions(self.executor.specs))
        if plan.resource_ids:
            request = await self._prefetch(principal, plan, request, context)
        before_run = getattr(self.session, 'before_run', None)
        if before_run is not None:
            await before_run(context)
        context.set_model_metadata(provider=getattr(self.gateway, 'provider', None), model=self.gateway.model)
        failures = protocol_failures = 0
        for decision_index in range(1, 13):
            context.raise_if_cancelled()
            self.executor.check_access()
            frame = self.session.before_decision()
            if frame.phase != 'advice':
                request = replace(request, messages=(*request.messages, {
                    'role': 'user', 'source': 'task_state',
                    'content': serialized({'revision': frame.revision, 'phase': frame.phase,
                                           'state': dict(frame.state)})}))
            if policy.organizes:
                # Bounded organisation of the rear only: the bodies of older
                # observations give way, their identity does not.
                request = replace(request, messages=organize_rear(
                    request.messages, max_chars=policy.max_chars))
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
                    # A permission revoked while waiting must be caught before
                    # the trusted state this round was built on is used.
                    latest = self.session.before_decision()
                    if latest.revision != frame.revision or latest.phase != frame.phase:
                        raise PermissionError('TASK_STATE_CHANGED')
                    return self.gateway.decide(request)
                response = await context.tool('agent_decision_model', 'safe', decide)
                decision = DecisionEnvelope.model_validate({'decision': response.decision}).decision
                context.consume_output(DecisionEnvelope(decision=decision).model_dump_json())
                # Observation only: a session never turns model text into a grant.
                self.session.after_decision(decision)
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
                after_tool = getattr(self.session, 'after_tool', None)
                if after_tool is not None:
                    await after_tool(context, observation)
                failures = failures + 1 if observation['status'] != 'ok' else 0
                if failures >= 2:
                    raise ValueError('AGENT_ACTION_FAILED')
                # Published Skills are workflow instructions of lower authority.
                # User records/knowledge are data, sanitized at each model ingress.
                payload = observation
                # The tool's declared effect decides whether its output must be
                # sanitized; the loop does not keep a list of tool names.
                if not observation.get('public'):
                    payload, _ = await context.step('context_guard', lambda: sanitize_context(
                        observation, default_pack(), scan_all=True))
                else:
                    await context.step('context_guard', lambda: None)
                request = replace(request, messages=(*request.messages,
                    {'role': 'assistant', 'content': decision.model_dump_json(), 'source': 'agent_action'},
                    {'role': 'user', 'content': serialized(payload), 'source': 'tool_data',
                     'revision': decision_index, 'call_id': decision.call_id,
                     'tool': decision.tool, 'status': observation.get('status', 'ok'),
                     'source_version': observation.get('source_version'),
                     'required_domains': list(observation.get('required_domains') or [])}))
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
                    # A source name alone cannot be checked against an answer. Carry the
                    # evidence id, chunk id and release so a citation is locatable and a
                    # claim about it is falsifiable.
                    sources.extend(
                        {
                            'source': item.get('source', ''),
                            'heading': item.get('heading', ''),
                            'evidence_id': item.get('evidence_id'),
                            'chunk_id': item.get('chunk_id'),
                            'release_id': item.get('release_id'),
                        }
                        for item in observation['data']
                    )
            metadata = {
                'scope': 'in_scope', 'llm_used': True, 'llm_answer_used': True,
                'agent_mode': 'unified', 'answer_contract': answer_contract(decision, self.executor, command),
                'answer_language': command.language or 'en-US', 'answer_mode': command.answer_mode or 'brief',
                'decision_count': decision_index, 'tool_attempts': self.executor.attempts,
                'tool_executions': self.executor.executions, 'tool_denials': self.executor.denials,
                'cache_hits': self.executor.cache_hits, 'protocol_failures': protocol_failures,
                'tool_calls': list(context.completed_tools), 'safety_outcome': verdict.outcome,
                'review_mode': self.review_mode,
                'context_policy_version': policy.version,
                'context_prefetched_resources': list(plan.resource_ids),
                'loaded_skill_ids': sorted({item['data']['resource_id'] for item in self.executor.observations.values()
                    if item['tool'] == 'resources.read' and item['status'] == 'ok'}),
            }
            result = AgentResult(answer, 'coach_advice', metadata, {}, tuple(sources), self.gateway.model)
            # The receipt is built by the session from persisted state, not by the
            # model, and is only present when a task actually produced one. An
            # answer the reviewer did not allow does not publish a candidate: the
            # task would otherwise look confirmable through text alone.
            receipt = self.session.before_delivery(decision) if verdict.outcome == 'allow' else {}
            return replace(result, task_receipt=dict(receipt)) if receipt else result
        raise BudgetExceeded('Agent decision budget exhausted')
