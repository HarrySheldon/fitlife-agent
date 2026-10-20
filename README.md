# FitLife Agent

FitLife Agent is a local-first fitness and nutrition application built with FastAPI, React and an explicit Python Agent runtime. Record meals and workouts, review trends, create validated plan drafts, and ask a contextual Coach for general lifestyle guidance.

## Start on Windows

From the repository root, with Docker Desktop installed:

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
~~~

The launcher creates an ignored local configuration when needed, preserves the deployment encryption key, starts the Compose services and waits for readiness.

- Frontend: http://127.0.0.1:3000
- Backend: http://127.0.0.1:8000
- Readiness: http://127.0.0.1:8000/health/ready
- API documentation: http://127.0.0.1:8000/docs

Useful commands:

~~~powershell
docker compose ps
docker compose logs --tail 100
docker compose down
~~~

Set host ports and matching browser origins through the existing launcher/Compose configuration. If changing the backend port, rebuild the frontend with matching API base URLs.

Docker builds use the official Python package index by default, with a 120-second timeout and five retries. In regions where PyPI downloads are unreliable, set a trusted HTTPS mirror in the untracked `.env` file before running the launcher:

```env
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
PIP_DEFAULT_TIMEOUT=120
PIP_RETRIES=5
```

## Try the unified coach window

The unified floating coach window (multi-chat, per-chat drafts, sources, collapsed trace, stop
and retry) ships behind two switches that are **off by default**. They must move together: the
window is compiled from `VITE_COACH_CONVERSATIONS_ENABLED`, while every conversation request is
checked against `COACH_CONVERSATIONS_ENABLED`. Turning on only the frontend opens the window but
every turn then fails with `409 COACH_CONVERSATIONS_DISABLED`.

The demo override turns both on without changing any default:

~~~powershell
docker compose -f docker-compose.yml -f docker-compose.coach.yml up --build -d
~~~

`--build` is required because `VITE_*` values are inlined at build time; changing them at runtime
has no effect. The window mounts for a signed-in user only.

To enable it permanently instead, set both keys in the untracked `.env` and rebuild:

~~~env
COACH_CONVERSATIONS_ENABLED=true
VITE_COACH_CONVERSATIONS_ENABLED=true
~~~

When running without Docker, note that Vite reads `.env` from `frontend/`, not from the repository
root. Create `frontend/.env` containing `VITE_COACH_CONVERSATIONS_ENABLED=true`, and start the
backend with `COACH_CONVERSATIONS_ENABLED=true` in its environment.

Why off by default: the C0 language fix must not depend on adopting the new entry, and the old
per-page coach drawer stays available as a fallback. See
`docs/evaluation/2026-10-20-c0-c4-delivery-record.md`.

## Run without Docker

Use an existing project virtual environment, or create one before installing dependencies:

~~~powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
~~~

In another terminal:

~~~powershell
Set-Location frontend
npm install
npm run dev
~~~

The development frontend is at http://127.0.0.1:5173. Do not regenerate sample data over an existing installation.

## Configure a model

Deterministic records, calculations and plan validation work without a model. For Agent features, sign in and open **Settings > Model connection** to configure and enable your own provider connection.

Follow the five steps: choose a provider, enter its HTTPS address and credential, discover or manually enter a model ID, explicitly test the current form, then save and enable. The single **Test connection** action checks generation and a minimal synthetic business-data parsing task; native tool calling is not an activation requirement. The page shows one overall result with collapsed technical details. Discovery is optional; a provider without a model-list endpoint can still be tested with a manually entered ID.

Saving a disabled draft preserves the active connection. Previewing or testing never saves configuration. Changing the address, protocol, model or credential invalidates the previous test; activation is also enforced by the backend with a short-lived configuration-bound receipt. Tests send at most two bounded synthetic requests and may incur provider charges; they never send your profile or health records. Loading settings and starting the application do not run these tests automatically.

Provider presets and protocol adapters are separate: another compatible provider can use the custom connection or a new preset without changing Agent workflows. This version supports the existing Responses and Chat Completions protocols, not every provider's native API. Custom connections use schema-guided JSON text and local Pydantic validation for both the parsing test and structured business calls, without requiring native strict-schema support. The actual official OpenAI connection preserves its native parsing path. DeepSeek Chat Completions uses `max_tokens` for bounded probes; no URL/model switching or automatic fallback is performed. Endpoints must be public HTTPS addresses; local/loopback model servers are not enabled by this change. Existing enabled connections remain usable, but enabling them again requires the current connection test. Old tool-check receipts cannot enable under the new rules. Passing a small sample does not guarantee full business quality; every business result is still validated. Configuration writes currently assume the existing single-process backend; multi-worker deployment needs transactional or cross-process configuration coordination first.

API keys are encrypted at rest. Keep the deployment's SETTINGS_ENCRYPTION_KEY stable and backed up securely; losing or rotating it without migration makes saved credentials unreadable. Never commit .env or print user API keys. The Windows launcher manages the deployment key; manual installations must set it before saving credentials.

Authenticated requests use only the signed-in user's enabled connection, with no fallback to a deployment key. The unauthenticated demo path can use the deployment's explicitly enabled model settings. Connection checks occur only when requested. Custom endpoints must satisfy the endpoint security policy.

## Product entry points

1. Register or sign in, then complete onboarding and explicitly confirm nutrition targets.
2. Use **Today** to draft meals, workouts or smart entries. Formal records require confirmation.
3. Use **Logbook** for dated records and optional CSV import.
4. Use **Review** for weekly trends and persisted reports.
5. Use **Plan** to generate, inspect and explicitly activate validated drafts.
6. Use the contextual **Coach** or **Chat** for analysis. Model suggestions do not directly write formal records.
7. Use **Profile** and **Settings** for personal preferences and account/model settings.

The developer **Evaluation** page is separate from ordinary product navigation. Explicit offline Mock and provider-backed Live evaluation, their limits and report formats are documented in the [Agent Runtime guide](docs/AGENT_RUNTIME.md#evaluation).

The new multi-chat floating Coach is behind two independent, default-off flags:
`COACH_CONVERSATIONS_ENABLED=true` on the backend and
`VITE_COACH_CONVERSATIONS_ENABLED=true` when building the frontend. Both must
agree; changing a Vite flag requires rebuilding the frontend image/bundle, not
just restarting it. Keep them off for the legacy UI. Before running code that
applies new database migrations to retained data, follow the verified backup
and isolation rules in AGENTS.md. Current implementation, offline evidence and
remaining manual acceptance checks are recorded in the
[C3 Coach report](docs/evaluation/2026-10-19-c3-coach-experience.md).

The initial Coach offline replay suite and its explicit coverage limits are in
[Coach acceptance](docs/evaluation/coach-conversation-acceptance.md). These Mock
cases do not authorize provider-backed tests or production activation.

## Data and backups

Business records use SQLite with per-user legacy cutover support; retained legacy CSVs and verified backups are recovery evidence, not files to delete casually. Runtime history is stored separately from business records.

Create a verified business database backup with:

~~~powershell
.venv\Scripts\python.exe scripts\backup_sqlite.py --output backups\fitlife.sqlite3
~~~

Also retain the deployment key and other user files required by your recovery procedure. See [data sources and storage](docs/data-sources.md).

## Maintainer documentation

- [Agent Runtime interfaces, configuration, safety, evaluation and tests](docs/AGENT_RUNTIME.md)
- [Domain terminology](UBIQUITOUS_LANGUAGE.md)
- [Data sources and provenance](docs/data-sources.md)
- [Catalog receiver design and commands](docs/superpowers/specs/2026-08-09-catalog-data-receiver-design.md)
- [Catalog localization and reproducible builds](docs/superpowers/specs/2026-08-11-mainland-catalog-localization-design.md)
- [Runtime refactor verification checkpoints](docs/superpowers/plans/agent-runtime-progress.md)

## Safety

FitLife provides general lifestyle information, not medical diagnosis, treatment, rehabilitation or disease-specific diet advice. Safety screening is a conservative rule-based baseline, not a clinically validated classifier. Urgent symptoms or immediate danger need appropriate professional or emergency help.
