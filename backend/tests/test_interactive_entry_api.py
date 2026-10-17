from backend.tests.test_smart_entry_api import client, reset_settings_cache, _register
from uuid import uuid4
from datetime import datetime
import pytest


BASE = '/api/v1/smart-entry-drafts'


def _create(client, monkeypatch, *, text='早餐：白飯 100g\n午餐：unknown-food'):
    monkeypatch.setenv('INTERACTIVE_ENTRY_ENABLED', 'true')
    from backend.config import get_settings
    get_settings.cache_clear()
    headers = _register(client, 'interactive-' + uuid4().hex[:10])
    draft = client.post(BASE, headers=headers,
        json={'log_date': '2026-07-26', 'raw_text': text}).json()['data']
    return headers, draft


def _post(client, headers, draft, route, body, key=None):
    return client.post(f"{BASE}/{draft['id']}/{route}",
        headers={**headers, 'Idempotency-Key': key or str(uuid4())}, json=body)


def test_interactive_contract_recovery_ownership_extra_fields_and_versions(client, monkeypatch):
    headers, draft = _create(client, monkeypatch)
    other = _register(client, 'foreign-' + uuid4().hex[:10])
    assert _post(client, other, draft, 'interaction/start', {'expected_version': 1}).status_code == 404
    assert _post(client, headers, draft, 'interaction/start', {'expected_version': 1, 'owner': 'evil'}).status_code == 422
    assert _post(client, headers, draft, 'interaction/start', {'expected_version': True}).status_code == 422
    assert client.post(f"{BASE}/{draft['id']}/interaction/start", headers=headers,
        json={'expected_version': 1}).status_code == 422
    key = str(uuid4())
    first = _post(client, headers, draft, 'interaction/start', {'expected_version': 1}, key)
    assert first.status_code == 200
    assert _post(client, headers, draft, 'interaction/start', {'expected_version': 1}, key).json()['data']['version'] == first.json()['data']['version']
    assert _post(client, headers, draft, 'interaction/start', {'expected_version': 1}).status_code == 409
    recovered = client.get(f"{BASE}/{draft['id']}", headers=headers).json()['data']
    assert recovered['version'] == first.json()['data']['version']
    assert recovered['agent_status'] == 'not_requested'
    item = recovered['payload']['interaction']['items'][0]
    assert _post(client, headers, draft, 'interaction/corrections', {'expected_version': recovered['version'],
        'item_id': item['item_id'], 'item_revision': item['revision'] + 1,
        'updates': {'amount': 50}}).status_code == 409
    assert _post(client, headers, draft, 'interaction/corrections', {'expected_version': recovered['version'],
        'item_id': item['item_id'], 'item_revision': item['revision'],
        'updates': {'state': 'saved'}}).status_code == 422
    assert _post(client, headers, draft, 'confirm-items', {'expected_version': recovered['version'],
        'selections': [{'item_id': item['item_id'], 'item_revision': item['revision'] + 1}]}).status_code == 409


def test_active_legacy_analysis_rejects_before_gateway(client, monkeypatch):
    headers, draft = _create(client, monkeypatch)
    started = _post(client, headers, draft, 'interaction/start', {'expected_version': 1}).json()['data']
    def forbidden(*args):
        raise AssertionError('legacy gateway must never resolve for active interaction')
    monkeypatch.setattr('backend.api.smart_entry.resolve_user_model_gateway', forbidden)
    response = client.post(f"{BASE}/{draft['id']}/analyze", headers={**headers,
        'If-Match': str(started['version'])})
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'INTERACTION_ANALYZE_NOT_ALLOWED'


@pytest.mark.parametrize('route,extra', [
    ('interaction/start', {}),
    ('interaction/answers', {'question_group_id': 'group', 'answers': []}),
    ('interaction/corrections', {'item_id': 'item', 'item_revision': 1, 'updates': {'amount': 10}}),
    ('confirm-items', {'selections': [{'item_id': 'item', 'item_revision': 1}]}),
])
def test_disabled_guards_existing_interaction_mutations_but_allows_resume(client, monkeypatch, route, extra):
    headers, draft = _create(client, monkeypatch)
    started = _post(client, headers, draft, 'interaction/start', {'expected_version': 1}).json()['data']
    monkeypatch.setenv('INTERACTIVE_ENTRY_ENABLED', 'false')
    from backend.config import get_settings
    get_settings.cache_clear()
    response = _post(client, headers, draft, route, {'expected_version': started['version'], **extra})
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'INTERACTIVE_ENTRY_DISABLED'
    assert client.get(f"{BASE}/{draft['id']}", headers=headers).status_code == 200


def test_ttl_snapshot_expired_read_and_foreign_privacy(client, monkeypatch):
    monkeypatch.setenv('ENTRY_TASK_TTL_DAYS', '4')
    headers, draft = _create(client, monkeypatch)
    expires = datetime.fromisoformat(draft['expires_at'].replace('Z', '+00:00'))
    created = datetime.fromisoformat(draft['created_at'].replace('Z', '+00:00'))
    assert 3.99 < (expires - created).total_seconds() / 86400 < 4.01
    monkeypatch.setenv('ENTRY_TASK_TTL_DAYS', '7')
    from backend.config import get_settings
    get_settings.cache_clear()
    assert client.get(f"{BASE}/{draft['id']}", headers=headers).json()['data']['expires_at'] == draft['expires_at']
    from backend.infrastructure.sqlite.runtime import get_database
    with get_database().transaction() as connection:
        connection.execute("UPDATE record_drafts SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (draft['id'],))
    assert client.get(f"{BASE}/{draft['id']}", headers=headers).status_code == 410
    other = _register(client, 'expired-foreign-' + uuid4().hex[:8])
    assert client.get(f"{BASE}/{draft['id']}", headers=other).status_code == 404


@pytest.mark.parametrize('error_type,status,code', [
    ('TaskBudgetExceeded', 409, 'TASK_BUDGET_EXHAUSTED'),
    ('BudgetExceeded', 429, 'RUN_BUDGET_EXCEEDED'),
])
def test_task_and_legacy_budget_errors_keep_distinct_public_status(client, monkeypatch, error_type, status, code):
    headers, draft = _create(client, monkeypatch)
    from backend.agent import runtime
    from backend.api.smart_entry import get_interactive_entry_service
    class ExhaustedService:
        def start(self, *args, **kwargs):
            raise getattr(runtime, error_type)('exhausted')
    client.app.dependency_overrides[get_interactive_entry_service] = lambda: ExhaustedService()
    try:
        result = _post(client, headers, draft, 'interaction/start', {'expected_version': 1})
        assert result.status_code == status
        assert result.json()['error']['code'] == code
    finally:
        client.app.dependency_overrides.pop(get_interactive_entry_service)


def test_answers_and_corrections_use_current_questions_and_preserve_explicit_null(client, monkeypatch):
    headers, draft = _create(client, monkeypatch, text='早餐：白飯')
    started = _post(client, headers, draft, 'interaction/start', {'expected_version': 1}).json()['data']
    interaction = started['payload']['interaction']
    item = interaction['items'][0]
    group = interaction['question_groups'][-1]
    result = _post(client, headers, draft, 'interaction/answers', {
        'expected_version': started['version'], 'question_group_id': group['group_id'],
        'answers': [{'item_id': item['item_id'], 'field': 'amount', 'value': 100},
                    {'item_id': item['item_id'], 'field': 'unit', 'value': 'g'}]})
    assert result.status_code == 200
    answered = result.json()['data']
    item = answered['payload']['interaction']['items'][0]
    assert item['state'] == 'ready'
    assert _post(client, headers, draft, 'interaction/answers', {
        'expected_version': answered['version'], 'question_group_id': 'obsolete',
        'answers': []}).status_code == 409
    cleared = _post(client, headers, draft, 'interaction/corrections', {
        'expected_version': answered['version'], 'item_id': item['item_id'],
        'item_revision': item['revision'], 'updates': {'amount': None}})
    assert cleared.status_code == 200
    latest = cleared.json()['data']
    item = latest['payload']['interaction']['items'][0]
    assert item['values']['amount'] is None
    assert item['state'] == 'needs_clarification'
    fixed = _post(client, headers, draft, 'interaction/corrections', {
        'expected_version': latest['version'], 'item_id': item['item_id'],
        'item_revision': item['revision'], 'updates': {'amount': 50}})
    assert fixed.status_code == 200
    item = fixed.json()['data']['payload']['interaction']['items'][0]
    assert item['state'] == 'ready'
    assert item['values']['amount'] == 50
    assert _post(client, headers, draft, 'confirm-items', {
        'expected_version': fixed.json()['data']['version'],
        'selections': [{'item_id': item['item_id'], 'item_revision': item['revision']}],
        'accepted_estimates': [{'item_id': item['item_id'], 'item_revision': item['revision'] + 1}]
    }).status_code == 422


def test_disabled_interaction_still_allows_separate_mixed_training_confirmation(client, monkeypatch):
    from backend.tests.test_smart_entry_api import _profile
    headers, draft = _create(client, monkeypatch,
        text='早餐：白飯 100g\n力量：杠铃深蹲 3x8 60kg')
    _profile(client, headers)
    started = _post(client, headers, draft, 'interaction/start', {'expected_version': 1}).json()['data']
    monkeypatch.setenv('INTERACTIVE_ENTRY_ENABLED', 'false')
    from backend.config import get_settings
    get_settings.cache_clear()
    response = client.post(f"{BASE}/{draft['id']}/confirm", headers={**headers,
        'If-Match': str(started['version']), 'Idempotency-Key': str(uuid4())})
    assert response.status_code == 200
    assert response.json()['data']['training_session_id'] is not None
    assert response.json()['data']['meal_ids'] == []
    resumed = client.get(f"{BASE}/{draft['id']}", headers=headers).json()['data']
    assert len(resumed['payload']['interaction']['items']) == 1
    assert resumed['payload']['interaction']['items'][0]['state'] == 'ready'


def test_recovery_reads_never_resolve_gateway_or_advance_version(client, monkeypatch):
    headers, draft = _create(client, monkeypatch)
    started = _post(client, headers, draft, 'interaction/start', {'expected_version': 1}).json()['data']
    def forbidden(*args):
        raise AssertionError('read must not resolve a provider')
    monkeypatch.setenv('LLM_ENABLED', 'true')
    from backend.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setattr('backend.api.smart_entry.resolve_user_model_gateway', forbidden)
    direct = client.get(f"{BASE}/{draft['id']}", headers=headers)
    latest = client.get(BASE, headers=headers, params={'date': draft['payload']['log_date']})
    assert direct.status_code == latest.status_code == 200
    assert direct.json()['data']['version'] == latest.json()['data']['version'] == started['version']
    assert direct.json()['data']['payload']['interaction'] == latest.json()['data']['payload']['interaction']


def test_start_reports_agent_mode_for_model_backed_interaction_snapshot(client, monkeypatch):
    from dataclasses import replace
    from backend.api.smart_entry import get_interactive_entry_service
    headers, draft = _create(client, monkeypatch, text='早餐：白飯 100g')
    service = get_interactive_entry_service()
    start = service.start
    def model_backed_start(*args, **kwargs):
        result = start(*args, **kwargs)
        return replace(result, payload=replace(result.payload, interaction=replace(
            result.payload.interaction, run_ids=('model-run',))))
    service.start = model_backed_start
    client.app.dependency_overrides[get_interactive_entry_service] = lambda: service
    try:
        response = _post(client, headers, draft, 'interaction/start', {'expected_version': 1})
        assert response.status_code == 200
        assert response.json()['processing_mode'] == 'agent'
    finally:
        client.app.dependency_overrides.pop(get_interactive_entry_service)


def test_interactive_capabilities_default_off_and_mutation_guard(client):
    headers = _register(client, 'interactive-default')
    base = '/api/v1/smart-entry-drafts'
    capabilities = client.get(f'{base}/capabilities', headers=headers)
    assert capabilities.status_code == 200
    assert capabilities.json()['data']['interactive_entry_enabled'] is False
    draft = client.post(base, headers=headers, json={
        'log_date': '2026-07-26', 'raw_text': '早餐：白飯 100g',
    }).json()['data']
    from uuid import uuid4
    result = client.post(f"{base}/{draft['id']}/interaction/start",
        headers={**headers, 'Idempotency-Key': str(uuid4())},
        json={'expected_version': draft['version']})
    assert result.status_code == 409
    assert result.json()['error']['code'] == 'INTERACTIVE_ENTRY_DISABLED'


def test_interactive_start_and_partial_commit(client, monkeypatch):
    monkeypatch.setenv('INTERACTIVE_ENTRY_ENABLED', 'true')
    from backend.config import get_settings
    get_settings.cache_clear()
    from uuid import uuid4
    headers = _register(client, 'interactive-partial')
    base = '/api/v1/smart-entry-drafts'
    draft = client.post(base, headers=headers, json={
        'log_date': '2026-07-26', 'raw_text': '早餐：白飯 100g\n午餐：unknown-food',
    }).json()['data']
    started = client.post(f"{base}/{draft['id']}/interaction/start",
        headers={**headers, 'Idempotency-Key': str(uuid4())},
        json={'expected_version': draft['version']})
    assert started.status_code == 200
    assert started.json()['processing_mode'] == 'deterministic'
    active = started.json()['data']
    assert active['payload']['interaction']['active'] is True
    ready = next(item for item in active['payload']['interaction']['items'] if item['state'] == 'ready')
    saved = client.post(f"{base}/{draft['id']}/confirm-items",
        headers={**headers, 'Idempotency-Key': str(uuid4())},
        json={'expected_version': active['version'], 'selections': [
            {'item_id': ready['item_id'], 'item_revision': ready['revision']}],
            'accepted_estimates': []})
    assert saved.status_code == 200
    resumed = client.get(f"{base}/{draft['id']}", headers=headers)
    assert resumed.status_code == 200
    assert len(resumed.json()['data']['item_commits']) == 1
    assert {item['state'] for item in resumed.json()['data']['payload']['interaction']['items']} == {'saved', 'needs_clarification'}
