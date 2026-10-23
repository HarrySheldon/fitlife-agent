import asyncio
from threading import Event
import pytest
from backend.agent.context_builder import ExecutionPrincipal
from backend.agent.decision import ToolCall
from backend.agent.runtime import RuntimeContext
from backend.agent.skills.catalog import SkillCatalog
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.handlers import BoundFitnessReads


class ForbiddenRepository:
    def read_profile(self, owner):
        raise AssertionError('Private data was read')

    read_workouts = read_profile
    read_meals = read_profile


def executor(domains=frozenset({'profile', 'training'}), authorize=None):
    principal = ExecutionPrincipal('owner', authorized_domains=domains)
    return ToolExecutor(principal=principal, reads=BoundFitnessReads(ForbiddenRepository(), 'owner'),
        catalog=SkillCatalog(), authorize=authorize or (lambda p: p.authorized_domains),
        retriever=lambda *a, **k: [], language='zh-CN')


def run_tool(ex, name, arguments, call_id='one'):
    return asyncio.run(ex.execute(ex.principal, ToolCall(call_id=call_id, tool=name, arguments=arguments), RuntimeContext()))


@pytest.mark.parametrize('tool,args', [
    ('delete_account', {}), ('shell', {'command': 'remove data'}),
    ('fitness.query', {'domain': 'profile', 'fields': ['goal'], 'user_id': 'other'}),
    ('fitness.query', {'domain': 'profile', 'fields': ['daily_protein_target']}),
    ('fitness.query', {'domain': 'diet', 'fields': ['food'], 'start_date': '2026-10-01', 'end_date': '2026-10-02'}),
    ('resources.read', {'resource_id': '../.env'}),
    ('fitness.calculate', {'operation': 'eval', 'code': 'delete()'}),
])
def test_dangerous_action_is_denied_without_reading(tool, args):
    ex = executor()
    assert run_tool(ex, tool, args)['status'] == 'denied'


def test_revoked_permission_denies_formerly_valid_query():
    ex = executor(authorize=lambda p: frozenset())
    assert run_tool(ex, 'fitness.query', {'domain': 'profile', 'fields': ['goal']})['status'] == 'denied'


def test_duplicate_id_denied_and_metadata_cache_rechecks_authority():
    ex = executor()
    assert run_tool(ex, 'skills.search', {'query': '训练'})['status'] == 'ok'
    assert run_tool(ex, 'skills.search', {'query': '训练'})['code'] == 'DUPLICATE_CALL_ID'
    assert run_tool(ex, 'skills.search', {'query': '训练'}, 'two')['status'] == 'ok'
    assert ex.cache_hits == 1


def test_shape_validated_suggestion_is_not_a_recorded_fact():
    ex = executor()
    result = run_tool(ex, 'fitness.calculate', {'operation': 'validate_training', 'exercises': [
        {'name': '俯卧撑', 'sets': 3, 'reps': 10, 'rest_seconds': 60}]})
    assert result['status'] == 'ok'
    assert result['data']['kind'] == 'suggestion'
    assert result['data']['clinical_safety_certified'] is False
    assert '3 组 × 10 次' in result['data']['suggestion_markdown']


def test_cancellation_prevents_even_public_tool_execution():
    from backend.agent.runtime import RunCancelled
    event = Event()
    event.set()
    ex = executor()
    with pytest.raises(RunCancelled):
        asyncio.run(ex.execute(ex.principal, ToolCall(call_id='a', tool='skills.search', arguments={'query': '训练'}),
                               RuntimeContext(cancel_event=event)))


def test_explicitly_excluded_domains_are_not_granted():
    from backend.agent.coach_composition import requested_domains
    from backend.agent.contracts import AgentCommand
    assert 'diet' not in requested_domains(AgentCommand('chat', '只安排训练，不要读取饮食记录', 'owner'))
    assert 'diet' not in requested_domains(AgentCommand('chat', 'Plan training, do not access my diet records', 'owner'))
    assert 'diet' not in requested_domains(AgentCommand('chat', '只给我训练建议，禁止访问饮食记录', 'owner'))
    assert 'diet' not in requested_domains(AgentCommand('chat', '只给我训练建议，无需查看饮食记录', 'owner'))
    assert 'diet' not in requested_domains(AgentCommand('chat', 'Only use training records. I do not consent to you accessing any of my diet records.', 'owner'))


def test_empty_authorized_records_keep_their_schema_for_calculation():
    import pandas as pd
    from backend.tools.workout_analyzer import REQUIRED_WORKOUT_COLUMNS
    class EmptyRepository:
        def read_workouts(self, owner):
            return pd.DataFrame(columns=REQUIRED_WORKOUT_COLUMNS)
    ex = executor()
    ex.reads = BoundFitnessReads(EmptyRepository(), 'owner')
    result = run_tool(ex, 'fitness.query', {'domain': 'training', 'fields': REQUIRED_WORKOUT_COLUMNS,
        'start_date': '2026-10-01', 'end_date': '2026-10-22'}, 'records')
    assert result['status'] == 'ok'
    result = run_tool(ex, 'fitness.calculate', {'operation': 'workout_analysis', 'input_ref': 'records'}, 'calc')
    assert result['status'] == 'ok'
    assert result['data']['total_strength_volume'] == 0


def test_empty_meals_and_incomplete_schema_have_distinct_results():
    import pandas as pd
    from types import SimpleNamespace
    from backend.tools.meal_analyzer import REQUIRED_MEAL_COLUMNS
    class EmptyRepository:
        def read_meals(self, owner):
            return pd.DataFrame(columns=REQUIRED_MEAL_COLUMNS)
        def read_profile(self, owner):
            return SimpleNamespace(model_dump=lambda: {'daily_calorie_target': 2000, 'daily_protein_target': 100})
    ex = executor(frozenset({'profile', 'diet'}))
    ex.reads = BoundFitnessReads(EmptyRepository(), 'owner')
    assert run_tool(ex, 'fitness.query', {'domain': 'profile', 'fields': ['daily_calorie_target', 'daily_protein_target']}, 'targets')['status'] == 'ok'
    assert run_tool(ex, 'fitness.query', {'domain': 'diet', 'fields': REQUIRED_MEAL_COLUMNS,
        'start_date': '2026-10-01', 'end_date': '2026-10-22'}, 'meals')['status'] == 'ok'
    result = run_tool(ex, 'fitness.calculate', {'operation': 'meal_analysis', 'input_ref': 'meals', 'targets_ref': 'targets'}, 'calc')
    assert result['status'] == 'ok'
    assert result['data']['weekly_average_calories'] == 0
    assert run_tool(ex, 'fitness.query', {'domain': 'diet', 'fields': ['date'],
        'start_date': '2026-10-01', 'end_date': '2026-10-22'}, 'partial')['status'] == 'ok'
    assert run_tool(ex, 'fitness.calculate', {'operation': 'meal_analysis', 'input_ref': 'partial', 'targets_ref': 'targets'}, 'bad')['status'] == 'denied'
