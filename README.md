# FitLife Agent

FitLife Agent is an open-source Agentic RAG project for personal fitness and diet management. It combines user profile data, meal records, workout records, a small Markdown knowledge base, deterministic Python analysis tools, a LangGraph-ready agent workflow, FastAPI APIs, and a React + Vite frontend.

The project is designed as a resume-ready AI Agent engineering internship portfolio project and a locally deliverable product. Its main loop is record-driven: register or log in, maintain meal and workout records from Today, review history and weekly trends, generate the next plan, and ask the contextual Coach for analysis without leaving the active workspace.

## What It Demonstrates

- Agent workflow design with a focused **FitLife Coach Agent**
- RAG over curated Markdown fitness and nutrition documents
- Tool calling with deterministic Python analyzers
- Per-user OpenAI or OpenAI-compatible model connections with explicit Responses or Chat Completions adapters
- Demo user management with username, email, or phone login, bearer-token sessions, and per-user local data files
- FastAPI backend with typed Pydantic schemas
- Today-first React + Vite + TypeScript frontend with contextual Coach actions
- Structured plan validation and Evaluation v2 reporting
- Docker Compose deployment path

## Architecture

```mermaid
flowchart LR
  UI["React + Vite Frontend"] --> API["FastAPI API"]
  API --> APP["Application Use Cases"]
  APP --> DOMAIN["Deterministic Domain Tools"]
  APP --> REPO["FitnessRepository"]
  AGENT["FitLife Coach Agent"] --> APP
  AGENT --> MODEL["ModelGateway"]
  REPO --> FILES["Per-user JSON / CSV"]
  MODEL --> OPENAI["OpenAI Responses API"]
  DOMAIN --> KB["Markdown Knowledge Base"]
```

The backend is a layered monolith. API handlers map transport concerns, application use cases coordinate work, deterministic domain tools calculate and validate facts, and infrastructure adapters implement persistence and model access.

## Agent Workflow

The MVP uses one top-level **FitLife Coach Agent**. Internal graph steps are nodes, not separate agents:

1. Planner classifies the user's intent.
2. Profile Loader reads the local user profile.
3. Data Analyzer calls meal or workout tools when required.
4. Retriever searches knowledge chunks when rules or substitutions are needed.
5. Plan Generator drafts next-week diet and workout plans.
6. Validator checks safety, preferences, allergies, rest days, and structure.
7. Report Writer returns concise Markdown plus trace metadata.

See [docs/AGENT_TERMINOLOGY_AND_DESIGN.md](docs/AGENT_TERMINOLOGY_AND_DESIGN.md) and [UBIQUITOUS_LANGUAGE.md](UBIQUITOUS_LANGUAGE.md) for the project vocabulary and Agent contract.

## Data Formats

`meals.csv` requires:

```text
date,meal,food,amount,calories,protein,carbs,fat
```

`workouts.csv` requires:

```text
date,type,exercise,muscle_group,sets,reps,weight,duration_min
```

`user_profile.json` includes height, weight, age, gender, goal, training frequency, preferences, restrictions, target weight, calorie target, and protein target.

The unauthenticated demo path reads `backend/data/*.csv` and `backend/data/user_profile.json`. After registration or login, API requests with a bearer token read and write `backend/data/users/<user_id>/...` so each local demo account has isolated profile, meal, and workout data. Registration asks the user to choose one primary identifier type: username, email, or phone. Login accepts any of those identifiers in one account field. Email and phone are local demo identifiers only; the app does not send verification emails or SMS messages.

### Records database

The backend creates `backend/data/fitlife.sqlite3` at startup and applies checksummed schema migrations. Set `SQLITE_DATABASE_PATH` only when the database must live elsewhere. CSV remains the active record source until the later migration phase; do not delete existing user CSV files.

## Local Setup

```bash
python scripts/generate_sample_data.py
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn backend.main:app --reload
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Backend: `http://127.0.0.1:8000`  
Frontend: `http://127.0.0.1:5173`

## Docker

```bash
docker compose up --build
```

Docker frontend: `http://127.0.0.1:3000`

Docker backend: `http://127.0.0.1:8000`

Set `FRONTEND_PORT` in `.env` to override the default host port when needed.

## Secure Model Configuration

Deterministic features are available without a model. Each authenticated user configures one model connection from **Settings > Model connection**. API keys are encrypted at rest and are never returned by the API.

Generate a deployment Fernet key once:

```powershell
.venv\Scripts\python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy `.env.example` to `.env` and set the generated value:

```env
SETTINGS_ENCRYPTION_KEY=<generated-fernet-key>
```

Do not commit `.env` or reuse the example as a real key. Losing or rotating this value without migration makes existing encrypted user API keys unreadable. When it is missing, deterministic features continue, saving a new API key fails with `CREDENTIAL_STORE_UNAVAILABLE`, and authenticated Agent requests cannot use stored credentials.

The deployment-level variables remain available only for the unauthenticated demo path:

```env
LLM_ENABLED=false
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=
EMBEDDING_MODEL=
```

An authenticated Agent request uses only that user's enabled encrypted connection and never falls back to `OPENAI_API_KEY`. Saving does not contact the provider. Model listing and connection testing run only after the user explicitly selects those actions. Custom endpoints are restricted to HTTPS public addresses and are revalidated before requests. API responses, logs, traces, and exports must not contain API key plaintext or ciphertext. Provider failures return stable errors such as `MODEL_TIMEOUT` or `MODEL_PROTOCOL_ERROR`; the system never presents a deterministic template as a successful Agent answer.

## Execution Boundaries

- Deterministic: profile and record persistence, Today and Dashboard calculations, calendar summaries, CSV import, weekly report generation, plan generation, and plan validation.
- Agent: Chat, contextual Coach interpretation, and Evaluation runs.
- Deterministic API responses include `processing_mode: deterministic`.
- Agent API responses include `processing_mode: agent`, `model`, and `request_id`.
- Agent failures do not alter or hide deterministic results.

The endpoint `/calendar/agent-entry` retains its current compatibility name, but its parser is deterministic and its response is marked accordingly. A future smart-input Agent flow must create a draft and require deterministic validation plus user confirmation before persistence.

## Product Flow

1. Start the backend and frontend.
2. Register or log in with a local username, email, or phone identifier.
3. Complete Profile with body state, goal, experience level, training focus, target mode, and restrictions.
4. Open Today and record a meal or workout with smart entry or a compact form.
5. Use the contextual Coach to explain daily progress, suggest the next meal, or adjust today's training.
6. Open Logbook to inspect calendar history, add records for an earlier date, or import CSV data.
7. Open Review to inspect trends, generate a weekly report, and ask the Coach to explain patterns.
8. Open Plan to generate and validate the next diet and training plan.
9. Use `/evaluation` separately when testing Agent quality; it is intentionally outside ordinary product navigation.

## Sample Questions

- 我这周蛋白质吃够了吗？
- 帮我总结这周饮食问题。
- 这周我的训练量相比上周有提升吗？
- 我不想吃鸡胸肉，有什么替代？
- 我想减脂，下周怎么安排训练？

## Evaluation

Run:

```bash
python scripts/run_eval.py --limit 5
```

Evaluation executes the real Agent path and therefore requires an enabled model connection.

Evaluation v2 reports:

- aggregate rates: pass rate, tool-call success, retrieval hit, structured output success, keyword coverage, validator pass;
- per-case checks: expected tool, retrieval source, keywords, answer format, validator status;
- failure reasons for each failed case;
- grouped metrics by expected tool and retrieval requirement.

Artifacts are written to:

- `backend/data/eval_results.json`
- `backend/data/eval_results.md`

The frontend Evaluation page calls `POST /eval/run` and renders the same aggregate metrics, group metrics, and failed-case details.

## Verification Report

See [docs/FINAL_VERIFICATION_REPORT.md](docs/FINAL_VERIFICATION_REPORT.md) for the latest verified command outputs, known warnings, and scope boundaries.

## Safety Note

FitLife Agent provides general lifestyle management suggestions only. It does not provide medical diagnosis, treatment, injury rehabilitation, or disease-specific diet guidance.

## Resume Bullets

- Built a LangGraph-based FitLife Coach Agent with deterministic tool calling, vector RAG, plan validation, and FastAPI endpoints for fitness and nutrition workflows.
- Implemented local-first Evaluation v2 with structured per-case graders, failure reasons, grouped metrics, and JSON/Markdown artifacts.
- Designed a Today-first React + Vite + TypeScript product with contextual Agent actions, calendar-based records, weekly review, validated plan generation, profile personalization, CSV import, and a separate developer evaluation surface.

## Chinese Resume Description

基于 LangGraph + FastAPI + React 构建 FitLife Agent 个人健身饮食规划智能体，整合用户饮食记录、训练记录和营养知识库，通过 RAG 检索饮食训练规则，并调用 Python 工具完成热量、宏量营养素、训练频率和训练容量分析。系统支持用户画像管理、自然语言问答、周报生成、饮食训练计划生成、计划校验和可视化 Dashboard。前端采用 React + Vite + TypeScript + Tailwind CSS 实现多页面交互界面，后端提供统一 FastAPI 接口，并通过自建评测集验证工具调用成功率、检索命中率和计划校验通过率。
