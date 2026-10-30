"""Regression evidence for the S3/S4 review, using only isolated synthetic data."""
import asyncio
import json
import pytest
from types import SimpleNamespace

from backend.tests.test_plan_adjustment_service import _service, _start, INSTRUCTIONS
from backend.tests.test_plan_adjustment_session import (
    _repository, _task, _session, StubValidation, _passed, _patch_arguments,
)


def test_repeated_execute_key_does_not_start_a_second_run(tmp_path):
    service, _, _, _ = _service(tmp_path)
    calls = []
    async def runner(session, binding, request):
        calls.append(request.instructions)
        return SimpleNamespace(answer=None, task_receipt=None, model='offline')
    service.runner = runner
    task = _start(service)
    async def run():
        first = await service.execute('alice', task['task_id'], task['version'], 'same-key', instructions=INSTRUCTIONS)
        second = await service.execute('alice', task['task_id'], task['version'], 'same-key', instructions=INSTRUCTIONS)
        assert second['replayed'] is True
        assert first['task'] == second['task']
    asyncio.run(run())
    assert len(calls) == 1


def test_a_candidate_without_a_reviewer_is_not_marked_reviewed(tmp_path):
    repo = _repository(tmp_path)
    task = _task(repo)
    session = _session(repo, task, StubValidation(_passed))
    session.submit_candidate(_patch_arguments()['patches'])
    with repo.database.connection() as connection:
        row = connection.execute('SELECT reviewed_digest FROM plan_adjustment_sessions').fetchone()
    assert row['reviewed_digest'] is None


def test_required_review_keeps_candidate_unconfirmable_until_it_actually_passes(tmp_path, monkeypatch):
    repo = _repository(tmp_path)
    task = _task(repo)
    session = _session(repo, task, StubValidation(_passed))
    session.review_mode = 'enforce'
    session.review_gateway = object()
    session.submit_candidate(_patch_arguments()['patches'])
    assert session.current().state == 'awaiting_user_decision'
    async def allow(*args):
        return SimpleNamespace(status='allow')
    monkeypatch.setattr('backend.agent.semantic_review.collect_review', allow)
    from backend.agent.runtime import RuntimeContext
    asyncio.run(session.after_tool(RuntimeContext(), {'tool': 'plan.submit_candidate', 'status': 'ok', 'data': {}}))
    assert session.current().state == 'awaiting_confirmation'


def test_task_frame_is_present_in_provider_input():
    from backend.agent.task_session import AdviceSession, SessionFrame
    from backend.agent.decision import FinalDecision
    from backend.tests.unified_coach.test_task_session import _run
    class Session(AdviceSession):
        def before_decision(self):
            return SessionFrame(2, 'repairing', {'failed_domains': ['diet'], 'violations': ['CONSTRAINT_REQUIRED']})
    _, gateway, _ = _run([FinalDecision(body='请先补充饮食限制。')], session=Session())
    frames = [json.loads(item['content']) for item in gateway.requests[0].messages if item.get('source') == 'task_state']
    assert frames[0]['state']['failed_domains'] == ['diet']


def test_expired_candidate_cannot_be_reviewed_or_delivered(tmp_path):
    from datetime import timedelta
    repo = _repository(tmp_path)
    task = _task(repo)
    session = _session(repo, task, StubValidation(_passed))
    session.submit_candidate(_patch_arguments()['patches'])
    expiry = session.current().candidate_expires_at
    repo.clock = lambda: expiry + timedelta(seconds=1)
    assert session.before_delivery(None) == {}
    with pytest.raises(Exception, match='expired'):
        repo.prepare_review('alice', task.task_id)


def test_legacy_review_stamp_does_not_skip_a_real_budgeted_review(tmp_path):
    from backend.tests.test_safety_review_integration import _Gateway, _allow
    from backend.agent.runtime import RuntimeContext
    repo = _repository(tmp_path)
    task = _task(repo)
    session = _session(repo, task, StubValidation(_passed))
    session.submit_candidate(_patch_arguments()['patches'])
    digest = session.current().candidate_digest
    with repo.database.transaction() as connection:
        connection.execute('UPDATE plan_adjustment_sessions SET reviewed_digest=?', (digest,))
    gateway = _Gateway(_allow())
    session.review_mode, session.review_gateway = 'enforce', gateway
    context = RuntimeContext()
    asyncio.run(session.before_run(context))
    assert gateway.calls == 1
    assert 'safety_review_model' in context.completed_tools
    assert session.current().state == 'awaiting_confirmation'


def test_failed_execute_is_not_repeated_under_the_same_key(tmp_path):
    service, _, _, _ = _service(tmp_path)
    calls = []
    async def runner(*args):
        calls.append(1)
        raise RuntimeError('offline failure')
    service.runner = runner
    task = _start(service)
    with pytest.raises(RuntimeError):
        asyncio.run(service.execute('alice', task['task_id'], task['version'], 'failed-key', instructions=INSTRUCTIONS))
    with pytest.raises(Exception, match='Read the task'):
        asyncio.run(service.execute('alice', task['task_id'], task['version'], 'failed-key', instructions=INSTRUCTIONS))
    assert len(calls) == 1
