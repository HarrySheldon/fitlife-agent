# OpenAI LLM Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional OpenAI-compatible LLM adapter for the FitLife Coach Agent without making local demo mode depend on network access or an API key.

**Architecture:** The adapter lives behind small `try_*` functions that return `None` when LLM execution is disabled, unavailable, or invalid. LangGraph planner and writer nodes use the adapter opportunistically, then fall back to deterministic rule routing and template writing. Tests use fake clients and never call the network.

**Tech Stack:** Python, Pydantic, OpenAI Python SDK, Responses API, LangGraph, pytest.

---

## References

- OpenAI Python SDK official README: `client.responses.create(model=..., instructions=..., input=...)`.
- OpenAI Python SDK structured output example: `client.responses.parse(..., text_format=SomePydanticModel)`.
- Existing project settings: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`.

## Acceptance Criteria

- Local tests and demo mode do not call OpenAI by default.
- `Settings` exposes `llm_enabled` and keeps API key/model/base URL configurable through `.env`.
- `backend/agent/llm_adapter.py` provides:
  - an adapter builder that lazy-imports `openai`;
  - structured route parsing into `PlannerRoute`;
  - optional final Markdown answer generation;
  - safe fallback behavior when disabled, malformed, or unavailable.
- `backend/agent/graph.py` uses:
  - LLM planner output when available;
  - deterministic `plan_route()` fallback otherwise;
  - LLM writer output when available;
  - deterministic `write_answer()` fallback otherwise.
- Trace includes whether the LLM path was used without changing existing evaluation fields.
- Existing backend tests and evaluation smoke still pass without an API key.

## Files

- Create: `backend/agent/llm_adapter.py`
  - OpenAI-compatible client wrapper and safe `try_*` functions.
- Modify: `backend/config.py`
  - Add `llm_enabled: bool = False`.
  - Keep model/base URL/API key fields.
- Modify: `.env.example`
  - Add `LLM_ENABLED=false`.
  - Keep `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL`.
- Modify: `requirements.txt`
  - Add `openai>=2.0.0`.
- Modify: `backend/agent/graph.py`
  - Call adapter in planner and writer nodes.
  - Include `llm_used` metadata in trace.
- Test: `backend/tests/test_llm_adapter.py`
  - Adapter disabled path.
  - Fake Responses `parse` route success.
  - Fake Responses `create` writer success.
  - Malformed output returns `None`.
- Test: `backend/tests/test_agent_graph.py`
  - Existing trace contract remains stable.
  - Writer/planner fallback keeps deterministic eval behavior.

## TDD Steps

1. Write failing adapter tests for disabled mode, fake route parsing, fake writer generation, and invalid output fallback.
2. Run `pytest backend\tests\test_llm_adapter.py -q -p no:cacheprovider` and verify failure because `backend.agent.llm_adapter` does not exist.
3. Implement `backend/agent/llm_adapter.py` with no network call unless `llm_enabled` and `openai_api_key` are both present.
4. Run adapter tests and make them pass.
5. Add graph integration tests for planner/writer fallback and trace metadata.
6. Update `backend/agent/graph.py` to call the adapter opportunistically.
7. Run graph tests.
8. Run all backend tests and eval smoke:

```powershell
..\..\.venv\Scripts\python -m pytest backend\tests -q -p no:cacheprovider
..\..\.venv\Scripts\python scripts\run_eval.py --limit 5
```

9. Commit and push `feat/openai-llm-adapter`.
