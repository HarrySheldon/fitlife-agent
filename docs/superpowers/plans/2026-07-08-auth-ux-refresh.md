# Auth UX Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the authentication page behave like a clearer product-grade demo login flow while keeping local username/email/phone password authentication.

**Architecture:** The backend keeps the existing bearer-token flow and local JSON user store, but updates auth error language so the public contract uses a generic account identifier. The frontend keeps a single `Auth` page and refactors the UI into a login form plus a registration form that asks the user to choose one primary identifier type instead of showing every identifier field at once.

**Tech Stack:** FastAPI, Pydantic, React, TypeScript, Vite, lucide-react, CSS.

---

### Task 1: Backend Auth Error Contract

**Files:**
- Modify: `backend/api/auth.py`
- Test: `backend/tests/test_auth_calendar_api.py`

- [ ] Add a failing API test that posts `/auth/login` with `identifier = "missing-user"` and asserts status `401` plus `detail = "Invalid account or password"`.
- [ ] Run `.\.venv\Scripts\python -m pytest backend\tests\test_auth_calendar_api.py::test_login_failure_uses_generic_account_error -q -p no:cacheprovider` and confirm it fails with the current `"Invalid email or password"` detail.
- [ ] Change the `HTTPException` detail in `backend/api/auth.py` to `"Invalid account or password"`.
- [ ] Re-run the targeted test and confirm it passes.

### Task 2: Product-Style Auth Form

**Files:**
- Modify: `frontend/src/pages/Auth.tsx`
- Modify: `frontend/src/styles/index.css`
- Modify: `frontend/src/types/index.ts`

- [ ] Replace the register form's simultaneous username/email/phone fields with an identifier type selector: `Username`, `Email`, `Phone`.
- [ ] Keep login as one `Username / email / phone` field plus password.
- [ ] Add show/hide password buttons using lucide icons and `type="button"`.
- [ ] Add inline demo-mode copy: email and phone are accepted as identifiers, but no verification code is sent.
- [ ] Add autocomplete/name attributes for password managers: `username`, `email`, `tel`, `current-password`, and `new-password`.
- [ ] Keep client validation: selected registration identifier and display name are required, password minimum is 8 characters.

### Task 3: Documentation And Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`

- [ ] Update docs to describe the identifier-type registration UI and the no-verification demo behavior.
- [ ] Run `.\.venv\Scripts\python -m pytest backend\tests -q -p no:cacheprovider` and confirm all backend tests pass.
- [ ] Run `npm run build` in `frontend` and confirm the TypeScript/Vite build passes.
- [ ] Run `git diff --check` and confirm no whitespace errors.
