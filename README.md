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
