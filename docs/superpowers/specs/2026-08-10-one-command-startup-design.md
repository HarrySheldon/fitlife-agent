# One-Command Startup Design

**Status:** Implemented and verified
**Date:** 2026-08-10
**Scope:** Secure local Windows PowerShell bootstrap and Docker Compose startup.

## Goal

Provide one documented command that prepares the local deployment secret, starts the complete Docker Compose application, waits for readiness, and prints the usable frontend and backend URLs.

## Command

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

The explicit process invocation works even when the user's PowerShell execution policy blocks direct execution of unsigned local scripts.

## Environment Bootstrap

The launcher resolves the repository root from its own location, so it works from any current directory. On the first run it copies `.env.example` to `.env`, generates one Fernet-compatible URL-safe Base64 key from 32 cryptographically random bytes, and writes it as `SETTINGS_ENCRYPTION_KEY`.

An existing non-empty key is reused. An invalid non-empty key is rejected instead of replaced, because replacing it would make previously encrypted user model credentials unreadable.

## Secret Boundaries

- Never print the key or include it in command arguments.
- Refuse to write when `.env` is tracked by Git.
- Refuse to write when the repository does not ignore `.env`.
- Write `.env` through a temporary file and same-directory replacement.
- Rely on the existing `**/.env*` Docker ignore rule and Dockerfiles that do not copy `.env`.
- Treat the launcher as a local-development path. Docker administrators can inspect container environment variables; production deployment requires a secret manager or Docker Secrets.

## Docker Lifecycle

The launcher requires the Docker CLI and Compose plugin. If the Docker engine is unavailable on Windows and Docker Desktop is installed at its standard path, it starts Docker Desktop and waits up to 120 seconds. It then runs `docker compose up --build -d`.

After Compose returns, the launcher polls backend `/health/ready` and the frontend root for up to 120 seconds. Success output contains only service status and URLs. Failure output identifies the failed phase and provides safe diagnostic commands without dumping environment variables.

## Testing

Pytest invokes the launcher with an internal `-InitializeOnly` switch inside temporary repositories. Tests prove first-run key creation, valid Fernet format, no secret output, idempotent reuse, invalid-key rejection, and ignore-rule enforcement. Compose configuration and a real startup provide integration evidence.

## Exclusions

- Bash, macOS, and Linux launchers;
- automatic port reassignment;
- production secret rotation or migration;
- printing Docker logs automatically;
- writing a user model API key.
