# One-Command Startup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a secure Windows PowerShell command that initializes the deployment encryption key, starts Docker Compose, waits for health, and documents the resulting URLs.

**Architecture:** `scripts/start.ps1` owns local bootstrap and process orchestration. It keeps secrets in the ignored `.env`, delegates application lifecycle to the existing Compose file, and exposes an initialization-only seam for deterministic tests.

**Tech Stack:** Windows PowerShell 5.1+, .NET cryptographic RNG, Docker Compose, pytest.

**Execution status:** Completed on 2026-08-10. Five focused tests passed, the PowerShell AST parsed without errors, a repeated launch preserved `.env`, backend readiness returned `ready`, and the frontend returned HTTP 200.

---

### Task 1: Specify Script Security Behavior

**Files:**
- Create: `backend/tests/test_start_script.py`

- [x] **Step 1: Write failing bootstrap tests**

Create temporary repository fixtures containing `.env.example`, `.gitignore`, and the launcher. Invoke PowerShell with `-InitializeOnly` and assert that the generated value is accepted by `cryptography.fernet.Fernet`, stdout does not contain it, a second run preserves it, an invalid existing key fails unchanged, and a missing `.env` ignore rule blocks creation.

- [x] **Step 2: Verify the tests fail**

Run: `python -m pytest backend/tests/test_start_script.py -q`

Expected: fail because `scripts/start.ps1` does not exist.

### Task 2: Implement Secure Startup

**Files:**
- Create: `scripts/start.ps1`

- [x] **Step 1: Implement environment initialization**

Resolve the project root from `$PSScriptRoot`, check Git tracking and ignore state, copy `.env.example` when required, generate a 32-byte cryptographically random Fernet key, validate existing keys, and replace `.env` atomically without printing the value.

- [x] **Step 2: Implement Docker lifecycle orchestration**

Check the Docker CLI, start Docker Desktop from its standard Windows path when needed, wait for `docker info`, run `docker compose up --build -d`, then poll backend and frontend URLs derived from `.env` or process environment overrides.

- [x] **Step 3: Run focused tests**

Run: `python -m pytest backend/tests/test_start_script.py -q`

Expected: all startup script tests pass.

### Task 3: Document And Verify The One-Command Flow

**Files:**
- Modify: `README.md`

- [x] **Step 1: Add the one-command startup section**

Place the robust PowerShell command before manual setup. Document first-run key behavior, stable URLs, safe reruns, health checks, stop and log commands, and the local-development Docker environment limitation.

- [x] **Step 2: Verify configuration and startup**

Run: `docker compose config --quiet`

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1`

Expected: Compose builds, both services become healthy, backend `/health/ready` succeeds, and the frontend returns HTTP 200.

- [x] **Step 3: Verify repository state**

Run: `git diff --check`

Run: `git status --short --branch`

Expected: only the planned script, test, README, spec, and plan files are changed; `.env` remains ignored.
