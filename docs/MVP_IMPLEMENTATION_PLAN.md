# FitLife Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable MVP of FitLife Agent that demonstrates Agentic RAG, deterministic Python tool calling, FastAPI APIs, React UI, structured validation, and automated evaluation.

**Architecture:** The backend exposes FastAPI routers and owns local data, analysis tools, RAG, and a LangGraph workflow. The frontend is a React + Vite + TypeScript client with pages for dashboard, upload, profile, chat, report, plan, and evaluation. The MVP uses local JSON/CSV storage and a replaceable vector-store abstraction.

**Tech Stack:** Python, FastAPI, Pydantic, Pandas, LangGraph, LangChain-compatible model interface, local vector retrieval, pytest, React, Vite, TypeScript, Tailwind CSS, Recharts, Docker Compose.

---

## Phase 0: Scaffold and Guardrails

### Task 0.1: Create Project Skeleton

**Files:**
- Create: `README.md`
- Create: `.env.example`
- Create: `requirements.txt`
- Create: `docker-compose.yml`
- Create: `backend/main.py`
- Create: `backend/config.py`
- Create: `backend/schemas.py`
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`

- [ ] Create the directory tree from `docs/PROJECT_SPEC.md`.
- [ ] Add `.env.example` with model provider variables: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `EMBEDDING_MODEL`, `APP_ENV`, `BACKEND_CORS_ORIGINS`.
- [ ] Add backend dependencies in `requirements.txt`: `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `pandas`, `python-multipart`, `pytest`, `httpx`, `langgraph`, `langchain`, and selected vector-store/embedding packages.
- [ ] Add frontend dependencies in `frontend/package.json`: `@vitejs/plugin-react`, `vite`, `react`, `react-dom`, `typescript`, `react-router-dom`, `recharts`, `tailwindcss`, and a Markdown renderer.
- [ ] Implement `GET /health` returning the standard API envelope.
- [ ] Run `python -m pytest` and confirm the test suite is discoverable, even before tests exist.
- [ ] Run `npm install` inside `frontend`, then `npm run build` after the first frontend skeleton exists.

### Task 0.2: Define Shared Backend Schemas

**Files:**
- Modify: `backend/schemas.py`
- Test: `backend/tests/test_schemas.py`

- [ ] Define `ApiResponse[T]` with `success`, `data`, and `message`.
- [ ] Define `UserProfile`, `MealRecord`, `WorkoutRecord`, `DashboardSummary`, `ChatRequest`, `ChatResponse`, `WeeklyReport`, `GeneratedPlan`, `ValidationResult`, and `EvalResult`.
- [ ] Add tests that instantiate each model with valid sample data.
- [ ] Add tests that invalid meal/workout records fail validation when required columns are missing or numeric fields are invalid.
- [ ] Run `python -m pytest backend/tests/test_schemas.py -q`.

## Phase 1: Sample Data and Deterministic Tools

### Task 1.1: Generate Demo Data

**Files:**
- Create: `scripts/generate_sample_data.py`
- Create: `backend/data/meals.csv`
- Create: `backend/data/workouts.csv`
- Create: `backend/data/user_profile.json`
- Create: `backend/data/eval_questions.json`

- [ ] Implement sample generation for 30 days of meal records with realistic foods and macros.
- [ ] Implement sample generation for 4 weeks of workout records with balanced muscle groups.
- [ ] Write one user profile targeting either fat loss, muscle gain, or maintenance.
- [ ] Write at least 20 evaluation questions covering meal tools, workout tools, RAG, plan generation, validation, and mixed questions.
- [ ] Run `python scripts/generate_sample_data.py`.
- [ ] Verify generated CSV headers exactly match the project spec.

### Task 1.2: Meal Analyzer

**Files:**
- Create: `backend/tools/meal_analyzer.py`
- Test: `backend/tests/test_meal_analyzer.py`

- [ ] Write failing tests for daily calories, daily macros, weekly average calories, weekly average protein, highest-calorie food, protein target compliance, calorie target compliance, and summary output.
- [ ] Implement pure functions that accept a `pandas.DataFrame` and profile target values.
- [ ] Make invalid CSV columns raise a typed `ValueError` with the missing column names.
- [ ] Run `python -m pytest backend/tests/test_meal_analyzer.py -q`.

### Task 1.3: Workout Analyzer

**Files:**
- Create: `backend/tools/workout_analyzer.py`
- Test: `backend/tests/test_workout_analyzer.py`

- [ ] Write failing tests for weekly training count, type distribution, total weekly duration, strength volume, undertrained muscle groups, week-over-week volume delta, and summary output.
- [ ] Implement pure functions that accept a `pandas.DataFrame`.
- [ ] Treat cardio rows with missing `sets`, `reps`, or `weight` as zero strength volume, not as invalid rows.
- [ ] Run `python -m pytest backend/tests/test_workout_analyzer.py -q`.

### Task 1.4: Profile Loader and Local File Store

**Files:**
- Create: `backend/tools/profile_loader.py`
- Test: `backend/tests/test_profile_loader.py`

- [ ] Implement `load_profile(path)` and `save_profile(path, profile)` using Pydantic validation.
- [ ] Add tests for loading valid profile JSON, rejecting invalid profile JSON, and preserving list fields like allergies and preferences.
- [ ] Run `python -m pytest backend/tests/test_profile_loader.py -q`.

## Phase 2: FastAPI Backend

### Task 2.1: API Router Structure

**Files:**
- Modify: `backend/main.py`
- Create: `backend/api/__init__.py`
- Create: `backend/api/health.py`
- Create: `backend/api/profile.py`
- Create: `backend/api/upload.py`
- Create: `backend/api/dashboard.py`
- Test: `backend/tests/test_api_basic.py`

- [ ] Create APIRouter modules and include them in `backend/main.py`.
- [ ] Add CORS configuration using `BACKEND_CORS_ORIGINS`.
- [ ] Implement `GET /health`.
- [ ] Implement `GET /profile` and `POST /profile`.
- [ ] Implement `POST /upload/meals` and `POST /upload/workouts` with `UploadFile`.
- [ ] Implement `GET /dashboard/summary` using meal and workout tools.
- [ ] Add API tests with `TestClient`.
- [ ] Run `python -m pytest backend/tests/test_api_basic.py -q`.

### Task 2.2: Report and Plan APIs

**Files:**
- Create: `backend/tools/report_generator.py`
- Create: `backend/agent/validator.py`
- Create: `backend/api/report.py`
- Create: `backend/api/plan.py`
- Test: `backend/tests/test_report_and_plan.py`
- Test: `backend/tests/test_validator.py`

- [ ] Implement weekly report generation from profile, meal analysis, and workout analysis.
- [ ] Implement deterministic plan generation fallback for no-LLM demo mode.
- [ ] Implement validator checks for calorie floor, protein/body-weight range, allergies/restrictions, training frequency, consecutive high-intensity days, rest days, and structured output.
- [ ] Implement `POST /report/weekly`.
- [ ] Implement `POST /plan/generate`.
- [ ] Run `python -m pytest backend/tests/test_report_and_plan.py backend/tests/test_validator.py -q`.

## Phase 3: Knowledge Base and RAG

### Task 3.1: Knowledge Documents

**Files:**
- Create: `backend/knowledge_base/nutrition_guidelines.md`
- Create: `backend/knowledge_base/fitness_rules.md`
- Create: `backend/knowledge_base/meal_templates.md`
- Create: `backend/knowledge_base/exercise_library.md`
- Create: `backend/knowledge_base/plan_rules.md`

- [ ] Write concise Markdown documents with stable section headings.
- [ ] Include source-friendly titles because retrieved snippets must cite document names.
- [ ] Keep advice general and avoid medical claims.
- [ ] Add practical examples that map to expected evaluation questions.

### Task 3.2: Retriever

**Files:**
- Create: `backend/rag/ingest.py`
- Create: `backend/rag/vector_store.py`
- Create: `backend/rag/retriever.py`
- Test: `backend/tests/test_retriever.py`

- [ ] Implement Markdown loading with document metadata.
- [ ] Implement chunking by headings and bounded character length.
- [ ] Implement local retrieval with deterministic fallback for no API key.
- [ ] Add tests that query protein, fat loss training, meal replacement, exercise safety, and plan rules.
- [ ] Verify each retrieval result includes `source`, `heading`, and `text`.
- [ ] Run `python -m pytest backend/tests/test_retriever.py -q`.

## Phase 4: LangGraph Agent

### Task 4.1: Graph State and Planner

**Files:**
- Create: `backend/agent/state.py`
- Create: `backend/agent/planner.py`
- Test: `backend/tests/test_agent_planner.py`

- [ ] Define explicit graph state fields listed in `docs/PROJECT_SPEC.md`.
- [ ] Implement planner output as structured data with `intent`, `needs_meal_analysis`, `needs_workout_analysis`, `needs_retrieval`, `needs_plan`, and `needs_report`.
- [ ] Add no-LLM keyword fallback for representative Chinese questions.
- [ ] Test questions such as "我这周蛋白质吃够了吗", "下周怎么安排训练", and "鸡胸肉有什么替代".
- [ ] Run `python -m pytest backend/tests/test_agent_planner.py -q`.

### Task 4.2: Agent Graph

**Files:**
- Create: `backend/agent/graph.py`
- Create: `backend/agent/retriever.py`
- Create: `backend/agent/generator.py`
- Create: `backend/agent/writer.py`
- Create: `backend/api/chat.py`
- Test: `backend/tests/test_chat_api.py`

- [ ] Build a LangGraph `StateGraph` with nodes: Planner, Profile Loader, Data Analyzer, Retriever, Plan Generator, Validator, Report Writer.
- [ ] Add conditional routing so pure knowledge questions can skip analysis and data questions can skip plan generation.
- [ ] Ensure final responses include Markdown and a compact trace with selected tools and sources.
- [ ] Implement `POST /chat`.
- [ ] Add API smoke tests for meal analysis, workout analysis, retrieval-only, plan generation, and mixed weekly summary.
- [ ] Run `python -m pytest backend/tests/test_chat_api.py -q`.

## Phase 5: Evaluation

### Task 5.1: Evaluation Runner

**Files:**
- Create: `scripts/run_eval.py`
- Create: `backend/api/eval.py`
- Test: `backend/tests/test_eval.py`

- [ ] Load `backend/data/eval_questions.json`.
- [ ] Call the agent or chat service for each question.
- [ ] Compute tool-call success, retrieval hit, structured-output success, preference compliance, validator pass, and total pass rate.
- [ ] Save latest result to `backend/data/eval_results.json`.
- [ ] Implement `POST /eval/run`.
- [ ] Run `python scripts/run_eval.py --limit 3` for a quick smoke test.
- [ ] Run `python -m pytest backend/tests/test_eval.py -q`.

## Phase 6: Frontend MVP

### Task 6.1: App Shell

**Files:**
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/routes/AppRoutes.tsx`
- Create: `frontend/src/components/Layout.tsx`
- Create: `frontend/src/components/Sidebar.tsx`
- Create: `frontend/src/styles/index.css`

- [ ] Configure Vite React entrypoint.
- [ ] Configure React Router routes for Dashboard, Upload, Profile, Chat, Weekly Report, Plan, and Evaluation.
- [ ] Build a responsive app shell with sidebar navigation.
- [ ] Add shared loading, error, and empty state components.
- [ ] Run `npm run build` inside `frontend`.

### Task 6.2: API Service and Types

**Files:**
- Create: `frontend/src/services/api.ts`
- Create: `frontend/src/types/index.ts`
- Create: `frontend/src/hooks/useDashboard.ts`
- Create: `frontend/src/hooks/useProfile.ts`
- Create: `frontend/src/hooks/useChat.ts`

- [ ] Mirror backend response and domain types.
- [ ] Centralize fetch calls and standard error handling.
- [ ] Add hooks for dashboard, profile, and chat flows.
- [ ] Ensure hooks expose `data`, `loading`, `error`, and action functions.
- [ ] Run `npm run build`.

### Task 6.3: Pages and Components

**Files:**
- Create: `frontend/src/components/MetricCard.tsx`
- Create: `frontend/src/components/FileUploader.tsx`
- Create: `frontend/src/components/ChatBox.tsx`
- Create: `frontend/src/components/ProfileForm.tsx`
- Create: `frontend/src/components/ReportViewer.tsx`
- Create: `frontend/src/components/PlanCard.tsx`
- Create: `frontend/src/components/ChartCard.tsx`
- Create: `frontend/src/pages/Dashboard.tsx`
- Create: `frontend/src/pages/Upload.tsx`
- Create: `frontend/src/pages/Profile.tsx`
- Create: `frontend/src/pages/Chat.tsx`
- Create: `frontend/src/pages/WeeklyReport.tsx`
- Create: `frontend/src/pages/Plan.tsx`
- Create: `frontend/src/pages/Evaluation.tsx`

- [ ] Dashboard shows four metric cards and chart cards from `/dashboard/summary`.
- [ ] Upload page uploads meals and workouts separately and shows success/error states.
- [ ] Profile page loads and saves user profile.
- [ ] Chat page sends user questions and renders Markdown replies.
- [ ] Weekly Report page calls `/report/weekly` and renders structured sections.
- [ ] Plan page calls `/plan/generate` and renders diet/workout cards plus validation warnings.
- [ ] Evaluation page calls `/eval/run` and renders metrics plus failed cases.
- [ ] Run `npm run build`.

## Phase 7: Docker, README, and Final Verification

### Task 7.1: Docker Compose

**Files:**
- Modify: `docker-compose.yml`
- Create: `backend/Dockerfile`
- Create: `frontend/Dockerfile`

- [ ] Build backend container with Uvicorn.
- [ ] Build frontend container with Vite production build served by a lightweight web server.
- [ ] Configure frontend API base URL for local Docker.
- [ ] Run `docker compose up --build`.
- [ ] Confirm `/health` and the frontend home page load.

### Task 7.2: README and Resume Packaging

**Files:**
- Modify: `README.md`

- [ ] Add project intro, background, real screenshot section after the UI exists, architecture diagram, workflow explanation, RAG explanation, tool calling explanation, frontend stack, data formats, local startup, Docker startup, sample questions, evaluation, project highlights, and resume-ready description.
- [ ] Add a "Demo script" section with the exact steps a reviewer should try.
- [ ] Add clear disclaimer that the app provides general lifestyle suggestions, not medical advice.
- [ ] Run all verification commands listed below.

### Task 7.3: Final Verification

**Commands:**

```bash
python scripts/generate_sample_data.py
python -m pytest backend/tests -q
python scripts/run_eval.py --limit 5
cd frontend && npm run build
docker compose config
```

- [ ] All backend tests pass.
- [ ] Frontend build passes.
- [ ] Evaluation smoke run completes and prints metrics.
- [ ] Docker Compose config is valid.
- [ ] README contains no fake screenshots, fake metrics, or hardcoded API keys.

## MVP Completion Checklist

- [ ] A new developer can run the backend from README instructions.
- [ ] A new developer can run the frontend from README instructions.
- [ ] Sample data is generated without private data.
- [ ] At least one meal-analysis question calls meal tools.
- [ ] At least one workout-analysis question calls workout tools.
- [ ] At least one substitution or rules question cites a knowledge document.
- [ ] Plan generation runs through the validator.
- [ ] Evaluation produces aggregate metrics and failed examples.
- [ ] The project can be described honestly in a resume without exaggerating production readiness.
