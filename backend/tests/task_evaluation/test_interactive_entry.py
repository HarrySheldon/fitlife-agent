"""Interactive runner contracts; no provider or production data is involved."""
import pytest

from backend.task_evaluation.contracts import Scenario
from backend.task_evaluation.runner import CaseError, _capture, execute_scenario


def test_response_observation_closed_metadata_and_missing_paths():
    from backend.task_evaluation.runner import _observe_response
    payload = {'data': {'version': 2, 'raw_text': 'PRIVATE', 'payload': {'interaction': {
        'clarification_rounds': 1, 'items': [{'state': 'ready', 'revision': 1}]}}}}
    assert _observe_response(payload, {'round': 'data.payload.interaction.clarification_rounds'}) == {'round': 1}
    for path in ('data.raw_text', 'data.payload.interaction.items.1.state', 'data.unknown'):
        with pytest.raises(CaseError):
            _observe_response(payload, {'fact': path})
    with pytest.raises(CaseError):
        _observe_response({'data': {'version': True}}, {'fact': 'data.version'})


def test_field_answers_use_actor_snapshot_actual_group_and_scripted_null():
    import httpx
    received = []
    def handler(request):
        import json
        if request.url.path.endswith('/answers'):
            received.append(json.loads(request.content))
            return httpx.Response(200, json={'data': {'version': 3}})
        return httpx.Response(200, json={'data': {'id': 'synthetic', 'version': 2, 'payload': {
            'interaction': {'question_groups': [{'group_id': 'dynamic-group', 'answered': False,
                'questions': [{'item_id': 'dynamic-item', 'field': 'amount'}]}]}}}})
    scenario = Scenario.model_validate({'id': 'field-answers', 'version': 1, 'steps': [
        {'method': 'GET', 'path': '/api/v1/smart-entry-drafts/synthetic'},
        {'method': 'POST', 'path': '/api/v1/smart-entry-drafts/synthetic/interaction/answers',
         'answer_by_field': {'amount': None}}]})
    with httpx.Client(transport=httpx.MockTransport(handler), base_url='http://test') as client:
        assert execute_scenario(scenario, client, headers_factory=lambda actor: {}).status == 'passed'
        assert received == [{'expected_version': 2, 'question_group_id': 'dynamic-group',
                             'answers': [{'item_id': 'dynamic-item', 'field': 'amount', 'value': None}]}]
        missing = scenario.model_copy(update={'steps': [scenario.steps[1]]})
        assert execute_scenario(missing, client, headers_factory=lambda actor: {}).status == 'unexpected_question'
        unknown = scenario.steps[1].model_copy(update={'answer_by_field': {'unit': None}})
        changed = scenario.model_copy(update={'steps': [scenario.steps[0], unknown]})
        assert execute_scenario(changed, client, headers_factory=lambda actor: {}).status == 'unexpected_question'


@pytest.mark.parametrize('returned_rounds', [0, 2])
def test_public_round_fault_fails_even_when_database_is_correct(returned_rounds):
    import httpx
    scenario = Scenario.model_validate({'id': 'dual-observation', 'version': 1, 'steps': [
        {'method': 'GET', 'path': '/api/v1/smart-entry-drafts/synthetic',
         'observe': {'public_rounds': 'data.payload.interaction.clarification_rounds'}}],
        'expected': {'public_rounds': 1, 'max_clarification_rounds': 1}})
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            'data': {'payload': {'interaction': {'clarification_rounds': returned_rounds}}}})), base_url='http://test') as client:
        result = execute_scenario(scenario, client, headers_factory=lambda actor: {},
                                  observer=lambda: {'max_clarification_rounds': 1})
    assert result.status == 'failed'
    assert result.failures == ('public_rounds',)


def test_public_item_state_fault_fails_even_when_database_is_correct():
    import httpx
    scenario = Scenario.model_validate({'id': 'dual-state', 'version': 1, 'steps': [
        {'method': 'GET', 'path': '/api/v1/smart-entry-drafts/synthetic',
         'observe': {'public_state': 'data.payload.interaction.items.0.state'}}],
        'expected': {'public_state': 'saved', 'item_states': ['saved']}})
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            'data': {'payload': {'interaction': {'items': [{'state': 'ready'}]}}}})), base_url='http://test') as client:
        result = execute_scenario(scenario, client, headers_factory=lambda actor: {},
                                  observer=lambda: {'item_states': ['saved']})
    assert result.status == 'failed'
    assert result.failures == ('public_state',)


def test_capture_indexes_dynamic_item_identity_and_numeric_revision():
    variables = {}
    assert _capture({"data": {"items": [{"id": "synthetic-item", "revision": 2}]}},
                    {"item": "data.items.0.id", "revision": "data.items.0.revision"}, variables) == {
                        "item": "synthetic-item", "revision": 2}
    for path in ("data.items.-1.id", "data.items.1.id", "data.items.bad.id"):
        with pytest.raises(CaseError):
            _capture({"data": {"items": [{"id": "synthetic-item"}]}}, {"item": path}, {})


def test_capabilities_are_explicit_and_unknown_requires_stay_unsupported():
    scenario = Scenario.model_validate({"id": "interactive-admission", "version": 1,
                                        "requires": ["interactive_entry"], "expected": {}})
    assert execute_scenario(scenario, None, headers_factory=lambda: {}).status == "unsupported"
    assert execute_scenario(scenario, None, headers_factory=lambda: {},
                            supported_capabilities={"interactive_entry"}).status == "passed"
    unknown = scenario.model_copy(update={"requires": ["future_unsupported"]})
    assert execute_scenario(unknown, None, headers_factory=lambda: {},
                            supported_capabilities={"interactive_entry"}).status == "unsupported"
