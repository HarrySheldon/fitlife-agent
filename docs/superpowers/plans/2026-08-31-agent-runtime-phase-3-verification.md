# Agent Runtime Phase 3 Verification

Date: 2026-09-10

## Delivered

- Memory and SQLite authoritative run repositories with append-only ordered events. Each state update and event append share a transaction and optimistic version check; terminal states reject further mutation.
- Dedicated `data_dir/agent_runtime.sqlite3`, real run metadata columns, and independent `PRAGMA user_version=1`. Unknown schema versions are rejected before schema writes. Business database migrations remain independent. Connections close after each transaction/read.
- A lazy production factory resolves the current settings path and assembles the sole production runtime. The legacy graph handle delegates to that factory. Tests replace the factory with isolated memory runtimes; a separate integration test invokes the real factory with temporary settings and reopens its SQLite database.
- Runtime acceptance, start, live step/attempt, tool start/finish, retry, cancellation request, and terminal events. Runs retain dates, policy snapshots, provider/model identifiers, input/output estimates, tool counts, public codes, internal error IDs and failure stages. Failure events carry the same internal error ID as the snapshot.
- Repository unavailability cannot return a successful outcome. Create/start/terminal failure injection verifies correlation IDs survive storage errors. Late worker results and checkpoints cannot change terminal state.
- Separate memory/SQLite checkpoint stores retain only completion and attempt metadata. They do not replay work automatically, infer recovery from trace, or store prompt/health/model response content. A process restart preserves existing run status and checkpoint metadata; resumption and orphan recovery are not implemented in this phase.
- Explicit no-op/in-memory telemetry with run, step, tool, AI request and retry spans, parentage, outcome and elapsed time. Run spans receive final input/output token estimates, tool/model counts and retry counts in `finally`, including failures. Adapter entry/exit/attribute failures are isolated; business errors cannot be suppressed and their sensitive cause/traceback never reaches the adapter.
- Event payloads use field/value allowlists; non-finite metrics, arbitrary exception types, raw text and credentials are rejected. Provider/model fields contain configuration identifiers only. Token values use the existing injected estimator, not provider billing usage; writer output is estimated without persisting its text.
- Evaluation cases now get distinct request IDs and retain a batch request ID, preserving the unique run/request contract. Full evaluation case isolation remains phase 5. Evaluation tests write only to temporary output paths.
- Completed process-cache entries remain bounded while historical repository status remains queryable; the former cache-eviction test now checks both requirements.

## Verification

Interpreter: `D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe` (pytest 9.1.1 verified before tests).

TDD checkpoints: original memory contract 1 passed; SQLite contract failed for missing adapter then 2 passed; runtime repository injection failed then the live execution/controls/deadline set passed 24; terminal repository failure lost correlation IDs, then its fix passed the persistence/telemetry set (21 tests). Additional tests cover reopen/checkpoint isolation, redaction, invalid metrics, real factory/settings changes, retry telemetry parentage, and late workers.

Acceptance command (worktree-local temporary directory):

```powershell
& 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe' -m pytest backend/tests/test_runtime_persistence.py backend/tests/test_agent_runtime_controls.py backend/tests/test_runtime_deadline_waits.py backend/tests/test_runtime_quality_review.py backend/tests/test_runtime_api_errors.py backend/tests/test_agent_runtime_workflow.py backend/tests/test_runtime_telemetry.py backend/tests/test_eval.py backend/tests/test_agent_graph.py backend/tests/test_agent_planner.py backend/tests/test_chat_api.py backend/tests/test_coach_api.py backend/tests/application/test_agent_boundary.py backend/tests/test_model_settings_api.py backend/tests/application/test_model_settings.py -q --basetemp=.tmp/phase3-final-acceptance
```

Final result: **114 passed**, one existing Starlette/httpx deprecation warning, 13.31 seconds, exit code 0. The earlier Agent acceptance set passed 96 tests and the persistence/model-settings follow-up passed 36. `git diff --check` passed. No real model/network calls or paid tokens were used. The full backend suite remains a final phase-5 acceptance requirement; this phase does not claim a clean full-suite rerun.

Phase 4 configuration resolution, hard safety gates and rate limits are not included. Phase 5 owns complete evaluation isolation and final interface documentation.
