"""A physical attempt that started must be visible even without a final event.

The previous accounting counted only completed logical decisions, so a handler
that started and was then torn down (or a worker that died mid-call) simply
disappeared from the report -- the same number as "never called". These tests
pin the difference.
"""
import asyncio
import sqlite3

import pytest

from backend.agent.contracts import AgentCommand, AgentResult
from backend.agent.runtime import AgentRuntime, RunCancelled
from backend.infrastructure.agent_runtime.sqlite_run_repository import SQLiteRunRepository
from backend.task_evaluation.metrics import runtime_metrics


def _result():
    return AgentResult(answer_markdown='ok', intent='chat', trace={}, tool_results={},
                       sources=(), model='synthetic')


def _repository(tmp_path):
    return SQLiteRunRepository(tmp_path / 'agent_runtime.sqlite3')


def test_started_handler_without_a_final_event_is_incomplete_not_absent(tmp_path):
    repository = _repository(tmp_path)

    class Workflow:
        async def execute(self, command, context):
            async def handler():
                # Torn down before any cleanup could run: this is the shape of a
                # cancellation or a worker crash, not of "the tool was never used".
                raise asyncio.CancelledError()
            await context.tool('fitness.query', 'safe', handler)

    async def scenario():
        with pytest.raises(RunCancelled):
            await AgentRuntime(repository=repository).execute(
                AgentCommand('chat', 'hello', 'u'), Workflow())

    asyncio.run(scenario())
    metrics = runtime_metrics(tmp_path)

    assert metrics['attempts_started'] == 1
    assert metrics['attempts_finished'] == 0
    assert metrics['attempts_incomplete'] == 1
    # No logical decision was ever recorded; that must not hide the attempt.
    assert metrics['tool_attempts'] == 0


def test_a_finished_attempt_is_not_reported_as_incomplete(tmp_path):
    repository = _repository(tmp_path)

    class Workflow:
        async def execute(self, command, context):
            await context.tool('fitness.query', 'safe', lambda: {'status': 'ok'})
            return _result()

    asyncio.run(AgentRuntime(repository=repository).execute(
        AgentCommand('chat', 'hello', 'u'), Workflow()))
    metrics = runtime_metrics(tmp_path)

    assert metrics['attempts_started'] == 1
    assert metrics['attempts_finished'] == 1
    assert metrics['attempts_incomplete'] == 0


def test_cache_hit_adds_a_logical_decision_but_no_physical_attempt(tmp_path):
    repository = _repository(tmp_path)

    class Workflow:
        async def execute(self, command, context):
            context.record('AGENT_TOOL_DECIDED', context, {
                'outcome': 'allow', 'cache_hits': 1,
                'agent_tool': 'skills.search', 'tool_executions': 0})
            return _result()

    asyncio.run(AgentRuntime(repository=repository).execute(
        AgentCommand('chat', 'hello', 'u'), Workflow()))
    metrics = runtime_metrics(tmp_path)

    assert metrics['cache_hits'] == 1
    assert metrics['tool_attempts'] == 1
    assert metrics['attempts_started'] == 0


def test_events_without_usage_are_reported_unknown_not_zero(tmp_path):
    with sqlite3.connect(tmp_path / 'agent_runtime.sqlite3') as db:
        db.execute("CREATE TABLE agent_runs(id,policy_version,attempt,started_at,"
                   "finished_at,status,policy_snapshot_json)")
        db.execute("CREATE TABLE agent_run_events(event_type,payload_json)")
        db.execute("INSERT INTO agent_runs VALUES('synthetic','policy-3',1,"
                   "'start','finish','succeeded','{}')")
        db.executemany("INSERT INTO agent_run_events VALUES(?,?)", [
            ('TOOL_STARTED', '{"tool":"other"}'),
            ('TOOL_FINISHED', '{"tool":"other","outcome":"succeeded"}'),
        ])

    metrics = runtime_metrics(tmp_path)

    assert metrics['attempts_finished'] == 1
    assert metrics['unknown_usage_count'] == 1
    assert metrics['known_total_tokens'] == 0


def test_provider_reported_tokens_are_summed_without_becoming_unknown(tmp_path):
    with sqlite3.connect(tmp_path / 'agent_runtime.sqlite3') as db:
        db.execute("CREATE TABLE agent_runs(id,policy_version,attempt,started_at,"
                   "finished_at,status,policy_snapshot_json)")
        db.execute("CREATE TABLE agent_run_events(event_type,payload_json)")
        db.execute("INSERT INTO agent_runs VALUES('synthetic','policy-3',1,"
                   "'start','finish','succeeded','{}')")
        db.executemany("INSERT INTO agent_run_events VALUES(?,?)", [
            ('TOOL_STARTED', '{"tool":"plan_route_model"}'),
            ('TOOL_FINISHED', '{"tool":"plan_route_model","outcome":"succeeded",'
                              '"usage_source":"provider","input_tokens":11,'
                              '"output_tokens":4}'),
        ])

    metrics = runtime_metrics(tmp_path)

    assert metrics['unknown_usage_count'] == 0
    assert metrics['known_total_tokens'] == 15
    assert metrics['usage_sources'] == ['provider']
