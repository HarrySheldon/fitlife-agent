# Settings Architecture Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the deterministic/Agent execution boundary, stable processing metadata and errors, and replace direct persistence/model dependencies with application ports without implementing user-facing settings yet.

**Architecture:** API handlers call focused application use cases. Use cases depend on `FitnessRepository` and `ModelGateway` protocols, while file persistence and the OpenAI Responses API remain infrastructure adapters. Deterministic endpoints never invoke a model; Agent endpoints require a configured gateway and never substitute deterministic prose for a failed model response.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pandas, LangGraph, OpenAI Python SDK, pytest, React/TypeScript.

---

### Task 1: Freeze the response and error contracts

**Files:**
- Create: `backend/domain/errors.py`
- Modify: `backend/schemas.py`
- Modify: `backend/api/utils.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_api_contracts.py`

- [x] **Step 1: Write failing response-contract tests**

```python
def test_ok_can_identify_deterministic_processing():
    assert ok({"value": 1}, processing_mode="deterministic")["processing_mode"] == "deterministic"


def test_application_error_uses_stable_code(client, monkeypatch):
    monkeypatch.setattr(agent_graph, "build_model_gateway", lambda: None)
    response = client.post("/chat", json={"question": "Help me"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AI_NOT_CONFIGURED"
```

- [x] **Step 2: Run tests and verify RED**

Run: `pytest backend/tests/test_api_contracts.py -q`

Expected: FAIL because `processing_mode`, `ApplicationError`, and its FastAPI handler do not exist.

- [x] **Step 3: Implement the contract**

Add `ProcessingMode = Literal["deterministic", "agent"]`, optional `processing_mode` and structured `ApiError` fields to `ApiResponse`. Define `ApplicationError(code, message, status_code)` and register one FastAPI exception handler that returns the existing response envelope without leaking third-party exception text.

- [x] **Step 4: Run tests and verify GREEN**

Run: `pytest backend/tests/test_api_contracts.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/domain/errors.py backend/schemas.py backend/api/utils.py backend/main.py backend/tests/test_api_contracts.py
git commit -m "feat: add stable processing and error contracts"
```

### Task 2: Introduce application ports and file repository adapter

**Files:**
- Create: `backend/application/ports/fitness_repository.py`
- Create: `backend/application/ports/model_gateway.py`
- Create: `backend/application/ports/__init__.py`
- Create: `backend/application/__init__.py`
- Create: `backend/infrastructure/repositories/file_fitness_repository.py`
- Create: `backend/infrastructure/repositories/__init__.py`
- Create: `backend/infrastructure/__init__.py`
- Modify: `backend/tools/data_access.py`
- Test: `backend/tests/application/test_ports.py`
- Test: `backend/tests/infrastructure/test_file_fitness_repository.py`

- [ ] **Step 1: Write failing port and isolation tests**

```python
def test_file_repository_keeps_users_isolated(tmp_path, settings_override):
    repository = FileFitnessRepository()
    repository.append_meal(
        MealRecord(
            date="2026-07-13",
            meal="lunch",
            food="rice and tofu",
            amount="1 serving",
            calories=520,
            protein=28,
            carbs=70,
            fat=14,
        ),
        "user-a",
    )
    assert len(repository.read_meals("user-a")) == 1
    assert repository.read_meals("user-b").empty


def test_fake_gateway_satisfies_model_gateway_protocol():
    gateway: ModelGateway = FakeGateway()
    assert gateway.write_answer({"user_query": "hello"}) == "answer"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest backend/tests/application/test_ports.py backend/tests/infrastructure/test_file_fitness_repository.py -q`

Expected: collection FAIL because the ports and adapter do not exist.

- [ ] **Step 3: Implement minimal ports and adapter**

`FitnessRepository` exposes profile, meal and workout reads plus profile/record writes. `ModelGateway` exposes `plan_route` and `write_answer`. `FileFitnessRepository` delegates the existing JSON/CSV behavior, and legacy `data_access` functions remain compatibility wrappers around the default adapter.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest backend/tests/application/test_ports.py backend/tests/infrastructure/test_file_fitness_repository.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/application backend/infrastructure backend/tools/data_access.py backend/tests/application backend/tests/infrastructure
git commit -m "refactor: add persistence and model gateway ports"
```

### Task 3: Move deterministic report and plan flows into application use cases

**Files:**
- Create: `backend/application/use_cases/generate_weekly_report.py`
- Create: `backend/application/use_cases/generate_plan.py`
- Create: `backend/application/use_cases/__init__.py`
- Modify: `backend/api/report.py`
- Modify: `backend/api/plan.py`
- Test: `backend/tests/application/test_deterministic_use_cases.py`
- Modify: `backend/tests/test_api_basic.py`

- [ ] **Step 1: Write failing no-network use-case tests**

```python
def test_weekly_report_is_deterministic(repository, exploding_gateway):
    result = GenerateWeeklyReport(repository).execute("user-a")
    assert result["title"]
    assert exploding_gateway.calls == 0


def test_report_api_marks_deterministic_processing(client):
    response = client.post("/report/weekly")
    assert response.json()["processing_mode"] == "deterministic"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest backend/tests/application/test_deterministic_use_cases.py backend/tests/test_api_basic.py -q`

Expected: FAIL because use cases and metadata do not exist.

- [ ] **Step 3: Implement use cases and thin handlers**

Each use case receives `FitnessRepository`, runs only deterministic analyzers/generators, and returns structured data. API handlers construct the file adapter, execute one use case, and call `ok(..., processing_mode="deterministic")`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest backend/tests/application/test_deterministic_use_cases.py backend/tests/test_api_basic.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/application/use_cases backend/api/report.py backend/api/plan.py backend/tests/application/test_deterministic_use_cases.py backend/tests/test_api_basic.py
git commit -m "refactor: isolate deterministic report and plan use cases"
```

### Task 4: Require a real model gateway for Agent execution

**Files:**
- Create: `backend/infrastructure/model_gateway/openai_responses.py`
- Create: `backend/infrastructure/model_gateway/__init__.py`
- Modify: `backend/agent/llm_adapter.py`
- Modify: `backend/agent/graph.py`
- Modify: `backend/agent/state.py`
- Modify: `backend/api/chat.py`
- Modify: `backend/api/coach.py`
- Test: `backend/tests/application/test_agent_boundary.py`
- Modify: `backend/tests/test_agent_graph.py`
- Modify: `backend/tests/test_llm_adapter.py`
- Modify: `backend/tests/test_chat_api.py`
- Modify: `backend/tests/test_coach_api.py`

- [ ] **Step 1: Write failing boundary tests**

```python
def test_agent_without_gateway_fails_instead_of_writing_template(monkeypatch):
    monkeypatch.setattr(agent_graph, "build_model_gateway", lambda: None)
    with pytest.raises(ApplicationError) as raised:
        run_fitlife_agent("Summarize my week")
    assert raised.value.code == "AI_NOT_CONFIGURED"


def test_coach_keeps_model_answer(monkeypatch, fake_gateway):
    result = run_contextual_coach_action("today", "explain_today", "2026-07-09", gateway=fake_gateway)
    assert result["answer_markdown"] == fake_gateway.answer
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest backend/tests/application/test_agent_boundary.py backend/tests/test_agent_graph.py backend/tests/test_chat_api.py backend/tests/test_coach_api.py -q`

Expected: FAIL because current code falls back to `plan_route`, `write_answer`, and `_deterministic_coach_answer`.

- [ ] **Step 3: Implement the explicit Agent boundary**

Build the environment-backed OpenAI adapter behind `ModelGateway`. Inject repository and gateway into graph nodes. Raise stable configuration/model errors when no gateway exists or invocation fails. Delete deterministic writer fallback and Coach answer replacement; deterministic tool output may be supplied as model context but never presented as a successful Agent answer.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest backend/tests/application/test_agent_boundary.py backend/tests/test_agent_graph.py backend/tests/test_llm_adapter.py backend/tests/test_chat_api.py backend/tests/test_coach_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/infrastructure/model_gateway backend/agent backend/api/chat.py backend/api/coach.py backend/tests
git commit -m "refactor: separate agent execution from deterministic fallback"
```

### Task 5: Expose processing metadata to frontend contracts and run regression checks

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/services/api.ts`
- Modify: `backend/tests/test_today_api.py`
- Modify: `README.md`

- [ ] **Step 1: Update contract assertions first**

Add backend assertions that deterministic endpoints return `processing_mode="deterministic"` and Agent endpoints return `processing_mode="agent"`. Add `ProcessingMode` and optional response error metadata to the frontend envelope type without changing existing page data return types.

- [ ] **Step 2: Run focused backend and frontend checks**

Run: `pytest backend/tests -q`

Expected: all backend tests PASS.

Run: `npm run build`

Working directory: `frontend`

Expected: TypeScript and Vite build PASS.

- [ ] **Step 3: Document the runtime boundary**

Document that `/report/weekly`, `/plan/generate`, dashboard and record calculations are deterministic, while `/chat` and `/coach/action` require a configured model. State explicitly that an Agent error never causes a template answer to be returned as AI output.

- [ ] **Step 4: Run final regression suite**

Run: `pytest backend/tests -q`

Run: `npm run build`

Expected: both PASS with no new warnings beyond known dependency warnings.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/services/api.ts backend/tests/test_today_api.py README.md
git commit -m "docs: expose execution mode across application contracts"
```
