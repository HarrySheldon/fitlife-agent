# Per-User Model Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each authenticated user securely configure, enable, inspect, explicitly test, and use one OpenAI or OpenAI-compatible model connection.

**Architecture:** A focused model-settings application service depends on a model-connection repository, credential cipher, endpoint policy, and provider gateway factory. File infrastructure stores only authenticated ciphertext with atomic replacement; Agent execution resolves the current authenticated user's connection and never falls back to deployment-wide credentials. The frontend exposes `/settings` as navigation and `/settings/model` as the isolated model task page.

**Tech Stack:** FastAPI, Pydantic v2, cryptography/Fernet, OpenAI Python SDK, httpx, pytest, React 19, TypeScript, React Router, lucide-react.

**Practice references:** Open WebUI explicit connection enablement and test actions, LiteLLM OpenAI-compatible adapter boundaries, and OpenAI Responses API migration guidance already recorded in the approved design specification.

---

### Task 1: Encrypted model connection storage

**Files:**
- Modify: `requirements.txt`
- Modify: `backend/config.py`
- Create: `backend/domain/model_connection.py`
- Create: `backend/application/ports/model_connection_repository.py`
- Create: `backend/application/ports/credential_cipher.py`
- Create: `backend/infrastructure/settings/fernet_cipher.py`
- Create: `backend/infrastructure/settings/file_model_connection_repository.py`
- Test: `backend/tests/infrastructure/test_model_connection_storage.py`

- [ ] Write failing tests proving per-user isolation, atomic JSON persistence, authenticated encryption, key retention, explicit key clearing, and zero plaintext/ciphertext in public views.
- [ ] Run the focused test and confirm RED because the domain model, cipher, and repository do not exist.
- [ ] Add `SETTINGS_ENCRYPTION_KEY`, strict Fernet key construction, a per-path process lock, temporary-file plus `os.replace` writes, and a stored/public model split.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit as `feat: add encrypted per-user model connection storage`.

### Task 2: Model settings application use cases and API

**Files:**
- Create: `backend/application/use_cases/model_settings.py`
- Create: `backend/api/settings.py`
- Modify: `backend/main.py`
- Modify: `backend/schemas.py`
- Test: `backend/tests/application/test_model_settings.py`
- Test: `backend/tests/test_model_settings_api.py`

- [ ] Write failing tests for GET, PUT, key deletion, authenticated user isolation, retaining omitted keys, resetting test state after material changes, and saving without any provider request.
- [ ] Run tests and confirm RED.
- [ ] Implement separate get/save/clear use cases and authenticated API handlers; saving a new key without a deployment cipher must return `CREDENTIAL_STORE_UNAVAILABLE`.
- [ ] Run tests and confirm GREEN.
- [ ] Commit as `feat: add per-user model settings api`.

### Task 3: Provider adapters, explicit test/list operations, and endpoint policy

**Files:**
- Modify: `backend/application/ports/model_gateway.py`
- Create: `backend/domain/model_endpoint_policy.py`
- Modify: `backend/infrastructure/model_gateway/openai_responses.py`
- Create: `backend/infrastructure/model_gateway/openai_chat_completions.py`
- Create: `backend/infrastructure/model_gateway/factory.py`
- Modify: `backend/application/use_cases/model_settings.py`
- Modify: `backend/api/settings.py`
- Test: `backend/tests/infrastructure/test_model_endpoint_policy.py`
- Test: `backend/tests/test_model_protocol_adapters.py`
- Modify: `backend/tests/test_model_settings_api.py`

- [ ] Write failing tests for HTTPS-only custom URLs, blocked credentials/query/fragment/private/metadata addresses, explicit protocol selection, unified planner/writer behavior, manual model listing, and a minimum tool-call connection probe.
- [ ] Run tests and confirm RED.
- [ ] Implement request-time DNS/IP validation, redirect-disabled bounded clients, Responses and Chat Completions adapters, and independent list/test use cases that store only normalized status.
- [ ] Run tests and confirm GREEN.
- [ ] Commit as `feat: add explicit model connection operations`.

### Task 4: Resolve Agent gateways per authenticated user

**Files:**
- Modify: `backend/agent/graph.py`
- Modify: `backend/infrastructure/model_gateway/factory.py`
- Modify: `backend/domain/errors.py`
- Test: `backend/tests/application/test_agent_boundary.py`
- Modify: `backend/tests/test_chat_api.py`
- Modify: `backend/tests/test_coach_api.py`

- [ ] Write failing tests proving a logged-in Agent uses only that user's enabled connection, ignores deployment credentials, returns `AI_DISABLED` for disabled settings, and returns `CREDENTIAL_STORE_UNAVAILABLE` when stored credentials cannot be decrypted.
- [ ] Run tests and confirm RED.
- [ ] Resolve environment credentials only for unauthenticated/demo execution and resolve encrypted per-user settings for authenticated execution.
- [ ] Run tests and confirm GREEN.
- [ ] Commit as `feat: connect agent execution to user model settings`.

### Task 5: Settings navigation and isolated model page

**Files:**
- Create: `frontend/src/pages/settings/SettingsHome.tsx`
- Create: `frontend/src/pages/settings/ModelSettings.tsx`
- Create: `frontend/src/hooks/useModelSettings.ts`
- Modify: `frontend/src/routes/AppRoutes.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/styles/index.css`

- [ ] Add frontend contract types and API methods without automatic model list or test calls.
- [ ] Build `/settings` as navigation-only rows with title, description, and chevron only; add `/settings/model` as the dedicated form task.
- [ ] Implement provider/protocol controls, manual model input, API-key retain/replace/clear states, explicit Save/Get models/Test buttons, disabled/loading/error/success states, and responsive layout.
- [ ] Run `npm run build` and inspect desktop/mobile routes in the browser.
- [ ] Commit as `feat: add model settings task pages`.

### Task 6: Security regression and delivery verification

**Files:**
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-07-13-user-model-settings.md`

- [ ] Add deployment documentation for generating and supplying `SETTINGS_ENCRYPTION_KEY`, with no repository default.
- [ ] Search tracked files, API payloads, logs, traces, and tests for plaintext keys or encrypted credential fields.
- [ ] Run all backend tests and the frontend production build.
- [ ] Exercise save, fetch, clear, disabled Agent, and missing-cipher API flows with TestClient.
- [ ] Commit as `docs: document secure user model settings`.

