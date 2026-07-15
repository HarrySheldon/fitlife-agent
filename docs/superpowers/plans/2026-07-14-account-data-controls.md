# Account and Data Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add isolated password, session, export, and account-deletion workflows with immediate session invalidation and secret-free portable exports.

**Architecture:** Account commands are independent application use cases over a locked file-backed identity store. Signed tokens carry `token_version`; password change and session revocation rotate it and issue a replacement token. Export builds an in-memory ZIP from an explicit allowlist, while deletion removes user-owned resources idempotently before deleting identity last.

**Tech Stack:** FastAPI, Pydantic v2, PBKDF2-HMAC, HMAC-signed bearer tokens, Python `zipfile`, React Router, Vitest.

**Practice references:** Django session-auth-hash invalidation (`django/contrib/auth/__init__.py`, `base_user.py`) and Immich's separate user-deletion service/API boundary.

---

### Task 1: Versioned identity store and session invalidation

**Files:**
- Create: `backend/application/ports/identity_repository.py`
- Create: `backend/infrastructure/auth/file_identity_repository.py`
- Modify: `backend/tools/auth_store.py`
- Modify: `backend/api/dependencies.py`
- Modify: `backend/schemas.py`
- Test: `backend/tests/infrastructure/test_identity_repository.py`
- Test: `backend/tests/test_session_versioning.py`

- [x] Write failing tests for locked atomic identity writes, legacy-user `token_version=0` migration, token-version validation, and rejection of older tokens after rotation. Evidence: vertical RED slices failed on missing repository, version, authentication, lifecycle, and token-claim behavior; replacement failure and malformed-hash cases were added during review.
- [x] Run focused tests and confirm RED. Evidence: each behavior failed before its implementation, including `KeyError: 'ver'`, rejected repository calls, six expiration/hash boundary failures, and the missing atomic replacement seam.
- [x] Implement a repository that owns users.json reads/writes and exposes authenticate, password replacement, version rotation, and identity deletion operations. Evidence: `FileIdentityRepository` serializes read-modify-replace operations with a per-path lock and same-directory atomic replacement; deployment remains constrained to one Uvicorn worker.
- [x] Add `ver` to newly issued tokens and compare it with the stored user on every authenticated request. Evidence: legacy tokens default to version zero, rotated identities reject earlier tokens, malformed claims fail closed, and `exp <= now` is rejected.
- [x] Preserve username/email/phone login and existing password hash compatibility. Evidence: existing 120,000-iteration PBKDF2 hashes remain valid while malformed and resource-abusive hashes fail safely.
- [x] Run focused tests and confirm GREEN. Evidence: 21 focused tests, 42 relevant auth/settings tests, and the complete backend suite of 167 tests pass; spec and code-quality reviews approved the result.
- [x] Commit as `refactor: add versioned identity sessions`. Evidence: implementation commit `1134e6a`, atomic-write test commit `20b6acf`, and hardening commit `4337cfb`.

### Task 2: Password change and revoke-other-session use cases

**Files:**
- Create: `backend/application/use_cases/account_security.py`
- Create: `backend/api/account.py`
- Modify: `backend/main.py`
- Modify: `backend/schemas.py`
- Test: `backend/tests/application/test_account_security.py`
- Test: `backend/tests/test_account_security_api.py`

- [x] Write failing tests proving current-password verification, new-password policy, version rotation, replacement token issuance, old-token rejection, and independent `POST /account/password/change` and `POST /account/sessions/revoke-others` handlers. Evidence: RED covered missing use cases/routes/localization, stale-principal races, and issuer failures before mutation.
- [x] Run focused tests and confirm RED. Evidence: missing routes returned 404, stale operations failed to raise, and account wiring initially lacked the authenticated claim version.
- [x] Implement separate change-password and revoke-other-session use cases; never accept a user ID from the request body. Evidence: both commands use an internal authenticated principal and atomic expected-version comparison; request schemas forbid extra identity fields.
- [x] Return a replacement `AuthSession` so the current browser remains signed in while all earlier tokens become invalid. Evidence: replacement sessions are pre-issued for the next version, committed only by successful compare-and-mutate, and stale requests receive 401 without resurrecting a session.
- [x] Run focused tests and confirm GREEN. Evidence: 47 focused tests and the full backend suite of 193 tests pass; spec and code-quality reviews approved the result.
- [x] Commit as `feat: add password and session controls`. Evidence: implementation commit `713ab75` and concurrency hardening commit `2b59998`.

### Task 3: Secret-free account export

**Files:**
- Create: `backend/application/use_cases/export_account_data.py`
- Modify: `backend/api/account.py`
- Modify: `backend/infrastructure/settings/file_model_connection_repository.py`
- Test: `backend/tests/application/test_export_account_data.py`
- Test: `backend/tests/test_account_export_api.py`

- [x] Write failing tests that open the returned ZIP and assert it contains identity metadata, profile, preferences, meals, workouts, and public model configuration but no password hash, token secret, API key plaintext, `encrypted_api_key`, or key hint. Evidence: plans/reports are not yet persisted, so no paths were invented; RED also covered symlinks, malformed data, size limits, formula injection, and allowlist bypass.
- [x] Run focused tests and confirm RED. Evidence: missing use case/route, unbounded files, unsafe CSV cells, and arbitrary extension sources failed before implementation.
- [x] Build the ZIP from an explicit filename/field allowlist using public model projection only; use deterministic archive paths and UTF-8 JSON. Evidence: the allowlist is closed, source snapshots are descriptor-validated, file/aggregate sizes are bounded, and malformed data fails with a sanitized stable error.
- [x] Add authenticated `GET /account/export` with attachment headers and no temporary plaintext archive on disk. Evidence: the response uses a fixed filename plus `Cache-Control: no-store` and `Pragma: no-cache`.
- [x] Run focused tests and confirm GREEN. Evidence: 29 focused tests and the complete backend suite of 222 tests pass; spec and security-quality reviews approved the result.
- [x] Commit as `feat: add private account data export`. Evidence: `7ddcfd7`, closed-allowlist fix `24bf46a`, and export hardening `dfb733e`.

### Task 4: Idempotent account deletion

**Files:**
- Create: `backend/application/use_cases/delete_account.py`
- Modify: `backend/api/account.py`
- Modify: `backend/schemas.py`
- Test: `backend/tests/application/test_delete_account.py`
- Test: `backend/tests/test_account_delete_api.py`

- [ ] Write failing tests for password re-entry, exact confirmation phrase, cross-user isolation, missing-file retries, model/data removal, identity-last ordering, and immediate rejection of the deleted user's token.
- [ ] Run focused tests and confirm RED.
- [ ] Implement an account deletion use case that verifies credentials, removes only the authenticated user's directory, tolerates already-missing owned files, and deletes identity last.
- [ ] Add authenticated `DELETE /account` without accepting target identity from the client.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit as `feat: add confirmed account deletion`.

### Task 5: Isolated security and privacy pages

**Files:**
- Create: `frontend/src/pages/settings/SecuritySettings.tsx`
- Create: `frontend/src/pages/settings/ChangePassword.tsx`
- Create: `frontend/src/pages/settings/SessionSettings.tsx`
- Create: `frontend/src/pages/settings/PrivacySettings.tsx`
- Create: `frontend/src/pages/settings/DeleteAccount.tsx`
- Modify: `frontend/src/pages/settings/SettingsHome.tsx`
- Modify: `frontend/src/routes/AppRoutes.tsx`
- Modify: `frontend/src/hooks/useAuth.tsx`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/styles/index.css`
- Test: `frontend/src/pages/settings/AccountSettings.test.tsx`

- [ ] Write route-level tests proving each task has isolated loading/error/success state, password inputs never persist, export downloads a ZIP, token replacement updates the current session, and account deletion clears auth only after success.
- [ ] Run focused tests and confirm RED.
- [ ] Build navigation-only `/settings/security`, dedicated password and session pages, `/settings/privacy` with export, and dedicated `/settings/privacy/delete` with password plus confirmation phrase.
- [ ] Add localized API methods and auth-session replacement/logout behavior.
- [ ] Run frontend tests/build and inspect desktop/mobile task routes.
- [ ] Commit as `feat: add account security and privacy tasks`.
