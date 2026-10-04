import pytest
from backend.configuration.models import RateLimitPolicy
from backend.infrastructure.agent_runtime.rate_limiter import ProcessRateLimiter, RateLimitExceeded


def test_rate_and_concurrency_share_user_bucket_across_operations_and_expire():
    now = [0.0]
    limiter = ProcessRateLimiter(clock=lambda: now[0])
    policy = RateLimitPolicy(requests_per_minute=2, concurrent_runs=1)
    lease = limiter.acquire("u", policy)
    with pytest.raises(RateLimitExceeded) as failure:
        limiter.acquire("u", policy)
    assert failure.value.retry_after_ms > 0
    lease.release()
    limiter.acquire("u", policy).release()
    with pytest.raises(RateLimitExceeded):
        limiter.acquire("u", policy)
    limiter.acquire("other", policy).release()
    now[0] = 61.0
    limiter.acquire("u", policy).release()


def test_rejected_run_has_persisted_failure_and_ids():
    import asyncio
    from backend.agent.contracts import AgentCommand, AgentResult
    from backend.agent.runtime import AgentRuntime
    from backend.configuration.resolver import ConfigurationResolver
    class Workflow:
        async def execute(self, command, context):
            return AgentResult("ok", "knowledge_qa", {}, {}, (), "mock")
    runtime = AgentRuntime(resolver=ConfigurationResolver(environment={"rate_limit": {"requests_per_minute": 1}}))
    asyncio.run(runtime.execute(AgentCommand("chat", "hello", "u"), Workflow()))
    with pytest.raises(RateLimitExceeded) as failure:
        asyncio.run(runtime.execute(AgentCommand("coach_action", "hello", "u", request_id="request-2"), Workflow()))
    error = failure.value
    assert error.request_id == "request-2"
    assert error.run_id
    snapshot = asyncio.run(runtime.get_status(error.run_id, "u"))
    assert snapshot.status == "failed"
    assert snapshot.public_error_code == "AGENT_RATE_LIMITED"


def test_bounded_cache_never_evicts_active_or_unexpired_buckets():
    now = [0.0]
    limiter = ProcessRateLimiter(clock=lambda: now[0], max_buckets=1)
    policy = RateLimitPolicy()
    lease = limiter.acquire(None, policy)
    with pytest.raises(RateLimitExceeded):
        limiter.acquire("u", policy)
    now[0] = 61.0
    with pytest.raises(RateLimitExceeded):
        limiter.acquire("u", policy)
    lease.release()
    limiter.acquire("u", policy).release()


def test_anonymous_callers_share_conservative_limit_and_lease_release_is_idempotent():
    limiter = ProcessRateLimiter()
    policy = RateLimitPolicy(anonymous_requests_per_minute=1)
    lease = limiter.acquire(None, policy)
    lease.release()
    lease.release()
    with pytest.raises(RateLimitExceeded):
        limiter.acquire("", policy)
    limiter.acquire("signed-in", policy).release()


def test_runtime_rate_failure_is_localized_at_http_boundary():
    from fastapi.testclient import TestClient
    from backend.main import create_app
    app = create_app()
    @app.get("/_test/agent-rate")
    def rate():
        raise RateLimitExceeded(1234)
    response = TestClient(app).get("/_test/agent-rate", headers={"accept-language": "zh-CN"})
    assert response.status_code == 429
    error = response.json()["error"]
    assert error["code"] == "AGENT_RATE_LIMITED"
    assert error["message"] == "Agent 请求过于频繁，请稍后重试。"
    assert error["retry_after_ms"] == 1234
    assert error["request_id"] == response.headers["x-request-id"]
