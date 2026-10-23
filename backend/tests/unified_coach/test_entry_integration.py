import pytest
from fastapi.testclient import TestClient
from backend.config import get_settings
from backend.agent import graph
from backend.agent.decision import DecisionEnvelope
from backend.application.ports.structured_model_gateway import StructuredModelResult
from backend.main import create_app


@pytest.mark.parametrize('entry', ['chat', 'contextual'])
def test_real_entry_uses_json_decisions_without_native_tools(tmp_path, monkeypatch, entry):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('SQLITE_DATABASE_PATH', str(tmp_path / 'fitlife.sqlite3'))
    monkeypatch.setenv('COACH_AGENT_MODE', 'unified')
    get_settings.cache_clear()

    class Gateway:
        model = 'fake-json-only'

        def parse_structured(self, **kwargs):
            assert kwargs['response_model'] is DecisionEnvelope
            return StructuredModelResult(DecisionEnvelope.model_validate({'decision': {
                'kind': 'ask', 'question': '你有哪些器械，是否有相关身体限制？'}}), self.model, {'total_tokens': 10})

        def plan_route(self, question):
            raise AssertionError('Old planner executed')

    monkeypatch.setattr(graph, '_resolve_gateway', lambda *a: Gateway())
    try:
        with TestClient(create_app()) as client:
            registration = client.post('/auth/register', json={'username': 'u-test', 'password': 'synthetic123456',
                                                               'display_name': 'Synthetic'}).json()['data']
            owner = registration['user']['user_id']
            headers = {'Authorization': 'Bearer ' + registration['access_token']}
            if entry == 'chat':
                response = client.post('/chat', headers=headers, json={
                    'question': '教练你好，我需要今天练胸，给出一份完整的训练计划', 'language': 'zh-CN'})
            else:
                response = client.post('/coach/action', headers=headers, json={
                    'surface': 'today', 'action': 'adjust_today_training',
                    'question': '今天练胸，给出训练计划', 'language': 'zh-CN'})
            assert response.status_code == 200, response.text
            result = response.json()['data']
            assert '器械' in result['answer_markdown']
            assert result['trace']['decision_count'] == 1
            assert 'tool_results' not in result
            assert result['trace']['agent_mode'] == 'unified'
    finally:
        get_settings.cache_clear()
