"""C4 regression: real final guard must not reintroduce Chinese boundary copy."""
import pytest


@pytest.mark.parametrize('language,question', [('en-US', 'Pick stocks'), ('zh-CN', '请推荐股票')])
def test_boundary_language_survives_all_runtime_guards(tmp_path, monkeypatch, language, question):
    from backend.config import get_settings
    from backend.agent import graph
    from backend.domain.coach_answer import message_catalog
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'isolated'))
    monkeypatch.setenv('SQLITE_DATABASE_PATH', '')
    monkeypatch.setenv('LLM_ENABLED', 'false')
    get_settings.cache_clear()
    def unexpected_gateway(*args, **kwargs):
        raise AssertionError('A deterministic boundary reply must not resolve a model')
    monkeypatch.setattr(graph, '_resolve_gateway', unexpected_gateway)
    try:
        result = graph.run_fitlife_agent(question, 'synthetic-boundary', language=language)
        assert result['answer_markdown'] == message_catalog(language).out_of_scope
        assert result['intent'] == 'business_scope'
    finally:
        get_settings.cache_clear()
