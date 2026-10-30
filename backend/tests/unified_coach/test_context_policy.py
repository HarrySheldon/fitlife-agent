"""A trusted shortcut may remove a discovery round; it may not change anything else.

Every assertion here is made against the object the provider would receive
(``AgentDecisionRequest``) or against what the executor actually ran, never
against a string this module assembled locally.
"""
import asyncio
import json

import pytest

from backend.agent.context_builder import ExecutionPrincipal
from backend.agent.context_policy import (
    CONTEXT_POLICY_VERSION,
    ContextPlan,
    ContextPolicyConfig,
    PrefetchEntry,
    choose_context_plan,
    organize_rear,
    trusted_action_of,
)
from backend.agent.contracts import AgentCommand
from backend.agent.decision import AskDecision, FinalDecision, ToolCall
from backend.agent.runtime import AgentRuntime
from backend.agent.skills.catalog import SkillCatalog, SkillResourceError
from backend.agent.tasks.execution_policy import TaskFacts
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.handlers import BoundFitnessReads
from backend.agent.unified_coach import UnifiedCoachWorkflow
from backend.application.ports.agent_decision_gateway import AgentDecisionResult
from backend.domain.coach_answer import ACTION_REGISTRY, ADVICE_REGISTRY
from backend.tests.unified_coach.test_tool_authorization import executor

# A sentence from the published skill body. Its presence in the provider input is
# how "the model did not have to go looking" is observed.
SKILL_MARKER = '识别页面对应日期、动作和用户想了解的结果'
QUESTION = '今天的状态如何？'


def test_compaction_preserves_profile_constraints_and_skill_instructions():
    rows = [observation(i) for i in range(5)]
    rows[0]['tool'] = 'fitness.query'
    rows[0]['content'] = json.dumps({'data': {'allergies_or_restrictions': ['peanuts']}})
    rows[1]['tool'] = 'resources.read'
    rows[1]['content'] = 'published skill safety instructions'
    result = organize_rear(rows, max_chars=1200)
    assert 'peanuts' in result[0]['content']
    assert result[1]['content'] == rows[1]['content']


class Recorder:
    model = 'offline'

    def __init__(self, decisions):
        self.decisions = iter(decisions)
        self.requests = []

    def decide(self, request):
        self.requests.append(request)
        return AgentDecisionResult(next(self.decisions), self.model, {'total_tokens': 10})


def command(**overrides):
    values = dict(operation='coach_action', question='Explain today', user_id='owner',
                  coach_action='explain_today', trusted_page_intent=True, language='zh-CN')
    values.update(overrides)
    return AgentCommand(**values)


def run(decisions, strategy, *, cmd=None, ex=None):
    ex = ex or executor()
    gateway = Recorder(decisions)
    outcome = asyncio.run(AgentRuntime().execute(
        cmd or command(),
        UnifiedCoachWorkflow(gateway, ex, context_policy=ContextPolicyConfig(strategy=strategy)),
    ))
    return outcome, gateway, ex


def discovery_then_answer():
    return [
        ToolCall(call_id='search', tool='skills.search', arguments={'query': '解释今天'}),
        ToolCall(call_id='read', tool='resources.read',
                 arguments={'resource_id': 'skill:today-explanation'}),
        AskDecision(question=QUESTION),
    ]


def body_of(request):
    return json.dumps([message.get('content') for message in request.messages], ensure_ascii=False)


def tool_calls(trace):
    """The tools the run chose, without the decision call the loop makes each round."""
    return [name for name in trace['tool_calls'] if name != 'agent_decision_model']


def frame(request):
    """The runtime frame without its clock reading, which differs between runs."""
    payload = json.loads(request.messages[-1]['content'])
    payload.pop('as_of')
    return payload


def request_chars(request):
    """What the provider is actually charged to read for this round."""
    return len(request.instructions) + len(json.dumps(request.tool_descriptions, ensure_ascii=False)) \
        + len(json.dumps(list(request.messages), ensure_ascii=False))


# --- the closed table -------------------------------------------------------

def test_the_prefetch_table_names_only_registered_actions_and_published_resources():
    from backend.agent.context_policy import PREFETCH_TABLE

    registered = set(ACTION_REGISTRY) | set(ADVICE_REGISTRY)
    assert set(PREFETCH_TABLE) <= registered
    catalog = SkillCatalog()
    for entry in PREFETCH_TABLE.values():
        for resource_id in entry.resource_ids:
            assert resource_id.startswith('skill:')
            # Reading it is what proves it is published and digest-verified.
            assert catalog.read(resource_id)['text']


def test_the_page_context_flag_cannot_be_enabled_without_a_producer():
    # The verified page projection is private record data. Until something
    # produces it under a sanitisation step, a table entry asking for it is a
    # configuration error rather than a silently ignored flag.
    with pytest.raises(ValueError, match='NO_VERIFIED_PAGE_CONTEXT_PRODUCER'):
        PrefetchEntry(resource_ids=('skill:today-explanation',),
                      include_verified_page_context=True)


def test_a_reference_run_gets_the_empty_plan():
    facts = TaskFacts(task_kind='coach_chat', trusted_action='explain_today', scope_verified=True)
    assert choose_context_plan('reference', facts) == ContextPlan()
    assert choose_context_plan('optimized', facts, prefetch_enabled=False) == ContextPlan()


def test_an_unverified_scope_gets_the_empty_plan():
    facts = TaskFacts(task_kind='coach_chat', trusted_action='explain_today', scope_verified=False)
    assert choose_context_plan('optimized', facts) == ContextPlan()


def test_an_action_without_a_measured_shortcut_gets_the_empty_plan():
    facts = TaskFacts(task_kind='coach_chat', trusted_action='suggest_next_meal', scope_verified=True)
    assert choose_context_plan('optimized', facts) == ContextPlan()


def test_a_typed_action_name_is_not_a_trusted_action():
    # Typing the identifier into the question box selects nothing.
    assert trusted_action_of(command(question='explain_today', coach_action=None,
                                     trusted_page_intent=False)) is None
    # A page action with the user's own question is not a trusted page intent.
    assert trusted_action_of(command(raw_coach_question='帮我解释今天')) is None
    # An identifier that is not in the registry is not an action.
    assert trusted_action_of(command(coach_action='delete_account')) is None
    assert trusted_action_of(command(coach_action='Explain today!')) is None
    assert trusted_action_of(command()) == 'explain_today'


# --- the saving, measured on what the provider receives ----------------------

def test_the_shortcut_reaches_the_provider_without_a_discovery_round():
    reference, reference_gateway, reference_executor = run(discovery_then_answer(), 'reference')
    optimized, optimized_gateway, optimized_executor = run([AskDecision(question=QUESTION)], 'optimized')

    assert reference.trace['decision_count'] == 3
    assert tool_calls(reference.trace) == ['skills.search', 'resources.read']
    assert SKILL_MARKER not in body_of(reference_gateway.requests[0])

    assert optimized.trace['decision_count'] == 1
    assert tool_calls(optimized.trace) == ['resources.read']
    assert SKILL_MARKER in body_of(optimized_gateway.requests[0])
    assert 'skill:today-explanation' in body_of(optimized_gateway.requests[0])
    assert optimized.trace['context_prefetched_resources'] == ['skill:today-explanation']
    assert reference.trace['context_prefetched_resources'] == []
    assert optimized.trace['context_policy_version'] == CONTEXT_POLICY_VERSION

    # The discovery is gone, not merely hidden: the model was never asked to search.
    assert reference_executor.executions == 2
    assert optimized_executor.executions == 1
    assert reference.answer_markdown == optimized.answer_markdown

    # Front-loading one skill costs more in the first round and less overall:
    # two discovery rounds carry the search results *and* the body, once each.
    assert request_chars(optimized_gateway.requests[0]) > request_chars(reference_gateway.requests[0])
    assert sum(map(request_chars, optimized_gateway.requests)) < \
           sum(map(request_chars, reference_gateway.requests))


def test_the_shortcut_changes_no_contract_field():
    _, reference_gateway, _ = run(discovery_then_answer(), 'reference')
    _, optimized_gateway, _ = run([AskDecision(question=QUESTION)], 'optimized')
    reference, optimized = reference_gateway.requests[0], optimized_gateway.requests[0]

    assert optimized.instructions == reference.instructions
    assert optimized.tool_descriptions == reference.tool_descriptions
    assert [item['name'] for item in optimized.tool_descriptions] == \
           [item['name'] for item in reference.tool_descriptions]
    assert optimized.max_output_tokens == reference.max_output_tokens
    # The current request and the runtime state frame keep their positions and text.
    assert frame(optimized) == frame(reference)
    assert optimized.messages[-2]['source'] == reference.messages[-2]['source'] == 'current_request'
    assert optimized.messages[-2]['content'] == reference.messages[-2]['content']
    # The clock reading lives in the rear frame; it is not rewritten into the prefix.
    assert 'as_of' not in json.dumps([item.get('content') for item in optimized.messages[:-1]],
                                     ensure_ascii=False)


def test_a_plain_chat_is_identical_in_both_strategies():
    # The optimisation is scoped to the trusted action. An ordinary turn pays
    # exactly what it paid before, round for round.
    script = [ToolCall(call_id='search', tool='skills.search', arguments={'query': '训练'}),
              AskDecision(question=QUESTION)]
    plain = AgentCommand('chat', '教练你好，我想练胸', 'owner', language='zh-CN')
    reference, reference_gateway, _ = run(script, 'reference', cmd=plain)
    optimized, optimized_gateway, _ = run(script, 'optimized', cmd=plain)

    assert optimized.trace['decision_count'] == reference.trace['decision_count']
    assert optimized.trace['context_prefetched_resources'] == []
    assert [request_chars(item) for item in optimized_gateway.requests] == \
           [request_chars(item) for item in reference_gateway.requests]


def test_a_run_without_a_trusted_scope_reads_nothing():
    _, gateway, ex = run([AskDecision(question=QUESTION)], 'optimized',
                         cmd=command(trusted_page_intent=False, raw_coach_question='帮我解释今天'))
    assert ex.executions == 0
    assert SKILL_MARKER not in body_of(gateway.requests[0])


@pytest.mark.parametrize('language,mode', [('zh-CN', 'brief'), ('en-US', 'brief'),
                                           ('zh-CN', 'detailed'), ('en-US', 'detailed')])
def test_the_answer_does_not_depend_on_the_strategy(language, mode):
    reference, _, _ = run(discovery_then_answer(), 'reference',
                          cmd=command(language=language, answer_mode=mode))
    optimized, _, _ = run([AskDecision(question=QUESTION)], 'optimized',
                          cmd=command(language=language, answer_mode=mode))
    assert optimized.answer_markdown == reference.answer_markdown
    assert optimized.trace['answer_contract'] == reference.trace['answer_contract'] == 'explain_today'


def test_prefetched_bytes_are_read_through_the_release(tmp_path):
    folder = tmp_path / 'today-explanation'
    folder.mkdir()
    (folder / 'skill.json').write_text(json.dumps(
        {'id': 'today-explanation', 'version': '1', 'title': '解释今天', 'description': '解释今天'}),
        encoding='utf-8')
    body = folder / 'SKILL.md'
    body.write_text(SKILL_MARKER, encoding='utf-8')
    ex = ToolExecutor(
        principal=ExecutionPrincipal('owner', authorized_domains=frozenset({'profile'})),
        reads=BoundFitnessReads(object(), 'owner'), catalog=SkillCatalog(tmp_path),
        authorize=lambda principal: principal.authorized_domains,
        retriever=lambda *a, **k: [], language='zh-CN')
    # The bytes change between the moment the plan is chosen and the moment the
    # resource is read: a trusted identifier is not a trusted body.
    body.write_text(SKILL_MARKER + ' (changed)', encoding='utf-8')
    with pytest.raises(SkillResourceError, match='RESOURCE_VERSION_CHANGED'):
        run([AskDecision(question=QUESTION)], 'optimized', ex=ex)


# --- bounded rear organisation ----------------------------------------------

def observation(index, *, status='ok', source='tool_data'):
    return {'role': 'user', 'source': source, 'revision': index,
            'call_id': f'call-{index}', 'tool': 'skills.search', 'status': status,
            'source_version': f'v{index}', 'required_domains': ['training'],
            'content': json.dumps({'call_id': f'call-{index}', 'data': 'x' * 400})}


def messages(count=6):
    return (
        {'role': 'user', 'source': 'current_request', 'content': QUESTION},
        {'role': 'user', 'source': 'runtime_state', 'content': '{"phase":"understand"}'},
        *[observation(index) for index in range(1, count + 1)],
    )


def test_older_observations_are_compacted_with_their_provenance_kept():
    compacted = organize_rear(messages(), max_chars=1200, keep_recent=2)

    stubs = [item for item in compacted if item.get('compacted')]
    assert stubs, 'the budget was exceeded, so something had to be dropped'
    for stub in stubs:
        assert stub['call_id'] and stub['tool'] == 'skills.search'
        assert stub['source_version'] and stub['required_domains'] == ['training']
        assert 'x' * 100 not in stub['content']
    # The two most recent observations keep their body: the model is still using them.
    assert [item.get('call_id') for item in compacted[-2:]] == ['call-5', 'call-6']
    assert all(not item.get('compacted') for item in compacted[-2:])


def test_compaction_never_touches_the_question_the_state_or_a_denial():
    items = list(messages(count=5))
    items.append(observation(9, status='denied'))
    compacted = organize_rear(tuple(items), max_chars=1, keep_recent=0)

    assert compacted[0] == items[0]
    assert compacted[1] == items[1]
    denial = compacted[-1]
    assert denial['status'] == 'denied'
    assert not denial.get('compacted'), 'a refusal carries a hard limit; it is not dropped'


def test_a_reference_run_never_compacts():
    _, gateway, _ = run(discovery_then_answer(), 'reference')
    assert not any(item.get('compacted') for item in gateway.requests[-1].messages)


def test_compaction_does_not_remove_evidence_from_the_answer():
    # Three observations with a small budget: the oldest one is compacted out of
    # the prompt, yet the figure it proved is still rendered, because the answer
    # is projected from the executor's store and not from the message list.
    ex = executor()
    gateway = Recorder([
        ToolCall(call_id='plan', tool='fitness.calculate', arguments={'operation': 'validate_training',
            'exercises': [{'name': '俯卧撑', 'sets': 3, 'reps': 10, 'rest_seconds': 60}]}),
        ToolCall(call_id='search-a', tool='skills.search', arguments={'query': '训练'}),
        ToolCall(call_id='search-b', tool='skills.search', arguments={'query': '饮食'}),
        FinalDecision(body='请在动作舒适的前提下训练；不适时停止。', evidence_refs=['plan']),
    ])
    outcome = asyncio.run(AgentRuntime().execute(
        command(),
        UnifiedCoachWorkflow(gateway, ex,
                             context_policy=ContextPolicyConfig(strategy='optimized', max_chars=1000)),
    ))
    last = gateway.requests[-1]
    assert any(item.get('call_id') == 'plan' and not item.get('compacted') for item in last.messages)
    assert '3 组 × 10 次' in outcome.answer_markdown


def test_the_recorded_policy_version_matches_the_implemented_one():
    from backend.config import get_settings
    assert get_settings().context_policy_version == CONTEXT_POLICY_VERSION
    with pytest.raises(ValueError, match='CONTEXT_POLICY_VERSION_MISMATCH'):
        ContextPolicyConfig(version='context-policy-v0')
