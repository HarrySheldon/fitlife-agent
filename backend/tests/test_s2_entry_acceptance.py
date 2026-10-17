"""Synthetic public API acceptance with independent read-only persistence facts."""
import json
from uuid import uuid4

from backend.config import get_settings
from backend.task_evaluation.contracts import Scenario
from backend.task_evaluation.observation import observe_database
from backend.task_evaluation.seeding import seed_environment
from backend.tests.task_evaluation.test_runner import _build_client, reset_settings_cache


def test_partial_save_reconnect_manual_completion_trace(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('INTERACTIVE_ENTRY_ENABLED', 'true')
    monkeypatch.setenv('LLM_ENABLED', 'false')
    client = _build_client(tmp_path, monkeypatch)
    settings = get_settings()
    scenario = Scenario.model_validate({'id': 'acceptance', 'version': 1, 'initial_state': {
        'catalog': {'foods': [{'source_record_id': 'acceptance-oats', 'name': 'S2wholemealOats',
                             'calories': 380, 'carbs': 60, 'protein': 13, 'fat': 7}]}}})
    actors = seed_environment(client, scenario, settings.data_dir)
    headers = actors['primary']
    base = '/api/v1/smart-entry-drafts'
    trace = []

    def facts(label, draft):
        stored = observe_database(settings.database_path, actors=actors.user_ids)
        entry = {'step': label, 'version': draft['version'],
                 'rounds': draft['payload']['interaction']['clarification_rounds'],
                 'formal_count': stored['confirmed_meals']}
        assert stored['draft_versions'] == [entry['version']]
        assert stored['max_clarification_rounds'] == entry['rounds']
        assert stored['item_states'] == [item['state'] for item in draft['payload']['interaction']['items']]
        assert stored['confirmed_workouts'] == 0
        trace.append(entry)

    def read():
        response = client.get(base + '/' + draft['id'], headers=headers)
        assert response.status_code == 200, response.json()
        return response.json()['data']

    def post(route, body):
        response = client.post(base + '/' + draft['id'] + '/' + route,
            headers={**headers, 'Idempotency-Key': str(uuid4())},
            json={'expected_version': draft['version'], **body})
        assert response.status_code == 200, response.json()
        return response.json()['data']

    response = client.post(base, headers=headers, json={'log_date': '2026-10-16',
        'raw_text': '早餐：S2wholemealOats 100g\n午餐：S2mysteryMilk'})
    assert response.status_code == 200
    draft = response.json()['data']
    facts('create', draft)
    draft = post('interaction/start', {})
    facts('start', draft)
    assert [item['state'] for item in draft['payload']['interaction']['items']] == ['ready', 'needs_clarification']
    group = draft['payload']['interaction']['question_groups'][-1]
    draft = post('interaction/answers', {'question_group_id': group['group_id'],
        'answers': [{'item_id': question['item_id'], 'field': question['field'], 'value': None}
                    for question in group['questions']]})
    facts('unknown_answers', draft)
    oats, milk = draft['payload']['interaction']['items']
    receipt = post('confirm-items', {'selections': [{'item_id': oats['item_id'], 'item_revision': oats['revision']}]})
    draft = read()
    assert receipt['remaining_draft_version'] == draft['version']
    facts('save_oats', draft)

    from backend.api.smart_entry import get_interactive_entry_service
    first_service = get_interactive_entry_service()
    replacement = get_interactive_entry_service()
    assert replacement is not first_service
    client.app.dependency_overrides[get_interactive_entry_service] = lambda: replacement
    recovered = read()
    assert recovered['version'] == draft['version']
    assert recovered['payload']['interaction'] == draft['payload']['interaction']
    draft = recovered
    facts('new_service_get_recovery', draft)
    milk = draft['payload']['interaction']['items'][1]
    draft = post('interaction/corrections', {'item_id': milk['item_id'], 'item_revision': milk['revision'],
        'updates': {'name': 'S2mysteryMilk', 'selected_catalog_id': None, 'amount': 200.0, 'unit': 'ml',
                    'basis_type': 'per_100ml', 'calories': 100.0, 'carbs': 10.0, 'protein': 6.0, 'fat': 4.0}})
    assert draft['payload']['interaction']['items'][1]['state'] == 'ready'
    facts('manual_correct_milk', draft)
    milk = draft['payload']['interaction']['items'][1]
    receipt = post('confirm-items', {'selections': [{'item_id': milk['item_id'], 'item_revision': milk['revision']}]})
    draft = read()
    assert receipt['remaining_draft_version'] == draft['version']
    facts('save_milk', draft)
    assert [entry['version'] for entry in trace] == [1, 2, 3, 4, 4, 5, 6]
    assert [entry['rounds'] for entry in trace] == [0, 1, 2, 2, 2, 2, 2]
    assert [entry['formal_count'] for entry in trace] == [0, 0, 0, 1, 1, 1, 2]
    assert observe_database(settings.database_path, actors=actors.user_ids)['item_commit_count'] == 2
    client.app.dependency_overrides.clear()
    with capsys.disabled():
        print('S2_ACCEPTANCE_TRACE=' + json.dumps(trace, separators=(',', ':')))
