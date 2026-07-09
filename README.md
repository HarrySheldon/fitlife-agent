# FitLife Agent

FitLife Agent is an open-source Agentic RAG project for personal fitness and diet management. It combines user profile data, meal records, workout records, a small Markdown knowledge base, deterministic Python analysis tools, a LangGraph-ready agent workflow, FastAPI APIs, and a React + Vite frontend.

The project is designed as a resume-ready AI Agent engineering internship portfolio project. It focuses on a working MVP loop: register or log in, maintain calendar-based meal and workout records, analyze records, retrieve knowledge, answer questions, generate weekly reports, generate next-week plans, validate plan safety, and run automated evaluation cases.

## What It Demonstrates

- Agent workflow design with a focused **FitLife Coach Agent**
- RAG over curated Markdown fitness and nutrition documents
- Tool calling with deterministic Python analyzers
- Optional OpenAI-compatible planner/writer and embedding adapters, disabled by default for local demos
- Demo user management with username, email, or phone login, bearer-token sessions, and per-user local data files
- FastAPI backend with typed Pydantic schemas
- React + Vite + TypeScript frontend
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

## Demo Script

1. Start the backend and frontend.
2. Register a local account by choosing username, email, or phone as the account identifier.
3. Open Records and add one meal, one workout, or one smart text entry for the selected date.
4. Open the Dashboard to inspect the selected day and current-week summary.
5. Ask the Chat page: `Did I hit my protein target this week?`
6. Ask: `What can replace chicken breast for protein?`
7. Generate a weekly report.
8. Generate a next-week plan and inspect validator output.
9. Run Evaluation and review grouped metrics plus failed-case details.

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
- Designed a React + Vite + TypeScript frontend with login/register, calendar-based record maintenance, dashboard analytics, chat, report generation, plan generation, profile management, CSV import, and evaluation review.

## Chinese Resume Description

基于 LangGraph + FastAPI + React 构建 FitLife Agent 个人健身饮食规划智能体，整合用户饮食记录、训练记录和营养知识库，通过 RAG 检索饮食训练规则，并调用 Python 工具完成热量、宏量营养素、训练频率和训练容量分析。系统支持用户画像管理、自然语言问答、周报生成、饮食训练计划生成、计划校验和可视化 Dashboard。前端采用 React + Vite + TypeScript + Tailwind CSS 实现多页面交互界面，后端提供统一 FastAPI 接口，并通过自建评测集验证工具调用成功率、检索命中率和计划校验通过率。
