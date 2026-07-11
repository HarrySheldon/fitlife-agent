# FitLife Agent

FitLife Agent is an open-source Agentic RAG project for personal fitness and diet management. It combines user profile data, meal records, workout records, a small Markdown knowledge base, deterministic Python analysis tools, a LangGraph-ready agent workflow, FastAPI APIs, and a React + Vite frontend.

The project is designed as a resume-ready AI Agent engineering internship portfolio project and a locally deliverable product. Its main loop is record-driven: register or log in, maintain meal and workout records from Today, review history and weekly trends, generate the next plan, and ask the contextual Coach for analysis without leaving the active workspace.

## What It Demonstrates

- Agent workflow design with a focused **FitLife Coach Agent**
- RAG over curated Markdown fitness and nutrition documents
- Tool calling with deterministic Python analyzers
- Optional OpenAI-compatible planner/writer and embedding adapters, disabled by default for local demos
- Demo user management with username, email, or phone login, bearer-token sessions, and per-user local data files
- FastAPI backend with typed Pydantic schemas
- Today-first React + Vite + TypeScript frontend with contextual Coach actions
- Structured plan validation and Evaluation v2 reporting
- Docker Compose deployment path

## Architecture

```mermaid
flowchart LR
  UI["React + Vite Frontend"] --> API["FastAPI Backend"]
  API --> Agent["FitLife Coach Agent"]
  Agent --> Planner["Planner"]
  Agent --> Tools["Meal/Workout Tools"]
  Agent --> RAG["Retriever"]
  Agent --> Validator["Validator"]
  Tools --> CSV["per-user meals.csv / workouts.csv"]
  RAG --> KB["Markdown Knowledge Base"]
  API --> Eval["Evaluation Runner"]
```

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

## Optional OpenAI Configuration

Local deterministic behavior is the default. OpenAI-compatible model calls are opt-in:

```env
LLM_ENABLED=false
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=
EMBEDDING_MODEL=
```

When `LLM_ENABLED=true` and an API key is available, the adapter can call an OpenAI-compatible Responses API for planner/writer behavior. If configuration is missing or a call fails, the agent falls back to deterministic local logic.

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
