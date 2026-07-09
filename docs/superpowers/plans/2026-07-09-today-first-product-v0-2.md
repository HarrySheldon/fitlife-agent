# Today-First Product v0.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize FitLife Agent from an MVP feature menu into a Today-first, record-driven product with coherent frontend navigation, backend page composition APIs, and contextual Agent actions.

**Architecture:** Keep the existing local data store, calendar APIs, dashboard summary, report generation, plan generation, and `/chat` endpoint. Add thin product-facing orchestration contracts for Today and contextual Coach actions, then refactor the React app around `Today / Logbook / Review / Plan / Profile`. Agent behavior remains backed by the existing LangGraph workflow, with context injected by a server-side Coach API instead of ad hoc frontend prompt strings.

**Tech Stack:** FastAPI, Pydantic, LangGraph workflow, local CSV/JSON store, React 19, React Router 7, Vite, TypeScript, Recharts, existing CSS.

---

## Practice Notes

The first version should optimize for daily recording and feedback loops:

- Open Food Facts shows that nutrition products benefit from structured food data and low-friction contribution flows.
- Foodbot identifies tedious manual food logging, weak food database coverage, and weak goal setting as core diet-app problems.
- FoodRepo highlights barcode/product databases as useful future infrastructure, but this version should not add barcode scanning.
- I Ate This reinforces that food journaling works better when capture is easy and feedback is tied to daily behavior.

For this project, the practical conclusion is: **do not add a large new database or image/barcode workflow yet**. First make the existing form, smart entry, calendar, analysis, and Agent feedback feel like one product loop.

Sources:

- Open Food Facts: https://world.openfoodfacts.org/
- Foodbot paper: https://arxiv.org/abs/2009.05704
- FoodRepo paper: https://arxiv.org/abs/1801.10195
- I Ate This paper: https://arxiv.org/abs/1702.05957

## File Map

### Backend

- Modify: `backend/schemas.py`
  - Add product-facing schemas: `ExperienceLevel`, `TrainingPreference`, `TodayOverview`, `TargetProgress`, `CoachActionRequest`, `CoachActionResponse`.
  - Extend `UserProfile` with product personalization fields while preserving backward-compatible defaults.
- Modify: `backend/tools/profile_loader.py`
  - Normalize old profile JSON files by filling missing v0.2 fields.
- Modify: `backend/tools/data_access.py`
  - Ensure user-scoped profile reads/writes preserve the new fields.
- Create: `backend/tools/target_suggestions.py`
  - Deterministically suggest calorie/protein targets from body state, goal, and training frequency.
- Create: `backend/tools/today_overview.py`
  - Compose daily detail, dashboard summary, target progress, and Coach action suggestions.
- Create: `backend/api/today.py`
  - Expose `GET /today?date=YYYY-MM-DD`.
- Create: `backend/api/coach.py`
  - Expose `POST /coach/action` for contextual Agent actions.
- Modify: `backend/main.py`
  - Register the new routers.
- Modify: `backend/agent/state.py`
  - Add optional `surface`, `coach_action`, and `context_date` fields for traces.
- Modify: `backend/agent/graph.py`
  - Add `run_contextual_coach_action(...)` wrapper around the existing graph.
- Test: `backend/tests/test_profile_personalization.py`
- Test: `backend/tests/test_today_api.py`
- Test: `backend/tests/test_coach_api.py`
- Update existing affected tests if schemas change.

### Frontend

- Modify: `frontend/src/types/index.ts`
  - Add Today, Coach, profile-personalization, and target-progress types.
- Modify: `frontend/src/services/api.ts`
  - Add `today(date)`, `coachAction(payload)`, and typed profile fields.
- Modify: `frontend/src/routes/AppRoutes.tsx`
  - Map `/` to Today, `/logbook` to Logbook, `/review` to Review, `/plan` to Plan, `/profile` to Profile.
  - Redirect legacy routes.
- Modify: `frontend/src/components/Sidebar.tsx`
  - Replace MVP feature nav with product nav.
  - Remove ordinary links to Upload, Evaluation, and Chat.
- Create: `frontend/src/components/CoachPanel.tsx`
  - Shared contextual Agent panel.
- Create: `frontend/src/components/TargetProgress.tsx`
  - Reusable calorie/protein/training progress display.
- Create: `frontend/src/hooks/useToday.ts`
  - Load Today overview and refresh after record changes.
- Create: `frontend/src/pages/Today.tsx`
  - New authenticated home page.
- Rename or create: `frontend/src/pages/Logbook.tsx`
  - Start from current `Records.tsx`, focused on calendar/history/import.
- Create: `frontend/src/pages/Review.tsx`
  - Combine trends and weekly report generation.
- Modify: `frontend/src/pages/Plan.tsx`
  - Convert single-button plan page into current/next plan workspace.
- Modify: `frontend/src/pages/Profile.tsx`
  - Organize profile, targets, onboarding fields, and settings.
- Modify: `frontend/src/components/ProfileForm.tsx`
  - Add v0.2 fields and system-suggested target display.
- Modify: `frontend/src/styles/index.css`
  - Product navigation, Today layout, Coach panel, responsive layout.

### Docs

- Modify: `README.md`
  - Update page names and user flow once implementation passes.
- Modify: `docs/IMPLEMENTATION_STATUS.md`
  - Record v0.2 scope and verification.

---

## Task 1: Backend Profile Personalization Foundation

**Files:**

- Modify: `backend/schemas.py`
- Modify: `backend/tools/profile_loader.py`
- Modify: `backend/tools/data_access.py`
- Create: `backend/tools/target_suggestions.py`
- Test: `backend/tests/test_profile_personalization.py`

- [ ] **Step 1: Add failing profile personalization tests**

Create `backend/tests/test_profile_personalization.py`:

```python
from backend.schemas import UserProfile
from backend.tools.target_suggestions import suggest_targets


def test_profile_accepts_v2_personalization_fields():
    profile = UserProfile(
        height_cm=178,
        weight_kg=82,
        age=28,
        gender="male",
        goal="fat_loss",
        weekly_training_frequency=4,
        allergies_or_restrictions=["peanut"],
        target_weight_kg=76,
        daily_calorie_target=2100,
        daily_protein_target=150,
        experience_level="novice",
        training_preference="mixed",
        target_mode="suggested",
    )

    assert profile.experience_level == "novice"
    assert profile.training_preference == "mixed"
    assert profile.target_mode == "suggested"


def test_target_suggestion_uses_goal_and_body_weight():
    profile = UserProfile(
        height_cm=178,
        weight_kg=82,
        age=28,
        gender="male",
        goal="fat_loss",
        weekly_training_frequency=4,
        target_weight_kg=76,
        daily_calorie_target=2100,
        daily_protein_target=150,
    )

    suggestion = suggest_targets(profile)

    assert 1600 <= suggestion.daily_calorie_target <= 2800
    assert 130 <= suggestion.daily_protein_target <= 180
    assert suggestion.source == "system"
    assert "fat loss" in suggestion.rationale.lower()
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
.\.venv\Scripts\python -m pytest backend\tests\test_profile_personalization.py -q -p no:cacheprovider
```

Expected: fails because `target_suggestions.py` and new schema fields do not exist.

- [ ] **Step 3: Extend `UserProfile` compatibly**

In `backend/schemas.py`, add:

```python
ExperienceLevel = Literal["beginner", "novice", "experienced"]
TrainingPreference = Literal["strength", "cardio", "mixed"]
TargetMode = Literal["suggested", "manual"]
```

Extend `UserProfile` with defaults:

```python
    experience_level: ExperienceLevel = "novice"
    training_preference: TrainingPreference = "mixed"
    target_mode: TargetMode = "suggested"
```

Do not remove existing `daily_calorie_target` or `daily_protein_target`; they remain the effective targets used by current analyzers.

- [ ] **Step 4: Add deterministic target suggestions**

Create `backend/tools/target_suggestions.py`:

```python
from pydantic import BaseModel

from backend.schemas import UserProfile


class TargetSuggestion(BaseModel):
    daily_calorie_target: int
    daily_protein_target: int
    source: str = "system"
    rationale: str


def suggest_targets(profile: UserProfile) -> TargetSuggestion:
    base = 10 * profile.weight_kg + 6.25 * profile.height_cm - 5 * profile.age
    if profile.gender == "male":
        base += 5
    elif profile.gender == "female":
        base -= 161
    activity_multiplier = 1.25 + min(profile.weekly_training_frequency, 6) * 0.05
    maintenance = int(base * activity_multiplier)

    if profile.goal == "fat_loss":
        calories = maintenance - 400
        rationale = "Fat loss target uses a moderate deficit from estimated maintenance."
    elif profile.goal == "muscle_gain":
        calories = maintenance + 250
        rationale = "Muscle gain target uses a conservative surplus from estimated maintenance."
    else:
        calories = maintenance
        rationale = "Maintenance target is based on estimated daily expenditure."

    protein_multiplier = 1.8 if profile.goal in {"fat_loss", "muscle_gain"} else 1.5
    protein = int(round(profile.weight_kg * protein_multiplier))

    return TargetSuggestion(
        daily_calorie_target=max(1200, min(5000, calories)),
        daily_protein_target=max(40, min(300, protein)),
        rationale=rationale,
    )
```

- [ ] **Step 5: Run tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest backend\tests\test_profile_personalization.py backend\tests\test_schemas.py backend\tests\test_profile_loader.py -q -p no:cacheprovider
```

Expected: pass. If existing profile-loader tests fail on exact dumps, update expected dictionaries to include the three default fields.

- [ ] **Step 6: Commit**

```powershell
git add backend\schemas.py backend\tools\target_suggestions.py backend\tests\test_profile_personalization.py backend\tests\test_schemas.py backend\tests\test_profile_loader.py
git commit -m "feat: add profile personalization fields"
```

---

## Task 2: Backend Today Overview API

**Files:**

- Modify: `backend/schemas.py`
- Create: `backend/tools/today_overview.py`
- Create: `backend/api/today.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_today_api.py`

- [ ] **Step 1: Add failing API test**

Create `backend/tests/test_today_api.py`:

```python
from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_today_overview_returns_daily_state():
    response = client.get("/today?date=2026-07-09")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["date"] == "2026-07-09"
    assert "summary" in data
    assert "meals" in data
    assert "workouts" in data
    assert "targets" in data
    assert "coach_actions" in data
```

- [ ] **Step 2: Run the failing test**

```powershell
.\.venv\Scripts\python -m pytest backend\tests\test_today_api.py -q -p no:cacheprovider
```

Expected: fails with 404 for `/today`.

- [ ] **Step 3: Add Today schemas**

In `backend/schemas.py`, add:

```python
class TargetProgress(BaseModel):
    label: str
    current: float
    target: float
    unit: str
    remaining: float
    status: Literal["under", "met", "over"]


class TodayOverview(BaseModel):
    date: str
    summary: DailySummary
    meals: list[MealRecord]
    workouts: list[WorkoutRecord]
    targets: list[TargetProgress]
    coach_actions: list[str]
```

- [ ] **Step 4: Implement Today composition**

Create `backend/tools/today_overview.py`:

```python
from backend.schemas import TargetProgress, TodayOverview, UserProfile
from backend.tools.calendar_store import get_daily_detail
from backend.tools.data_access import read_profile


def build_today_overview(day: str, user_id: str | None = None) -> TodayOverview:
    profile = read_profile(user_id)
    detail = get_daily_detail(day, user_id)
    summary = detail.summary
    return TodayOverview(
        date=day,
        summary=summary,
        meals=detail.meals,
        workouts=detail.workouts,
        targets=[
            _progress("Calories", summary.calories, profile.daily_calorie_target, "kcal"),
            _progress("Protein", summary.protein, profile.daily_protein_target, "g"),
            _progress("Training", summary.training_sessions, 1 if profile.weekly_training_frequency else 0, "sessions"),
        ],
        coach_actions=_coach_actions(profile, summary.training_sessions),
    )


def _progress(label: str, current: float, target: float, unit: str) -> TargetProgress:
    remaining = target - current
    status = "met" if remaining <= 0 else "under"
    if label == "Calories" and current > target * 1.1:
        status = "over"
    return TargetProgress(label=label, current=current, target=target, unit=unit, remaining=remaining, status=status)


def _coach_actions(profile: UserProfile, training_sessions: int) -> list[str]:
    actions = ["explain_today", "suggest_next_meal"]
    if training_sessions == 0 and profile.weekly_training_frequency > 0:
        actions.append("adjust_today_training")
    return actions
```

- [ ] **Step 5: Expose `/today` router**

Create `backend/api/today.py`:

```python
from datetime import date as date_type

from fastapi import APIRouter, Depends

from backend.api.dependencies import optional_current_user
from backend.api.utils import ok
from backend.schemas import AuthenticatedUser
from backend.tools.today_overview import build_today_overview


router = APIRouter()


@router.get("/today")
def today(date: str | None = None, user: AuthenticatedUser | None = Depends(optional_current_user)):
    day = date or date_type.today().isoformat()
    overview = build_today_overview(day, user.user_id if user else None)
    return ok(overview.model_dump())
```

Register it in `backend/main.py` with the existing routers.

- [ ] **Step 6: Run API tests**

```powershell
.\.venv\Scripts\python -m pytest backend\tests\test_today_api.py backend\tests\test_auth_calendar_api.py backend\tests\test_api_basic.py -q -p no:cacheprovider
```

Expected: pass.

- [ ] **Step 7: Commit**

```powershell
git add backend\schemas.py backend\tools\today_overview.py backend\api\today.py backend\main.py backend\tests\test_today_api.py
git commit -m "feat: add today overview API"
```

---

## Task 3: Backend Contextual Coach API

**Files:**

- Modify: `backend/schemas.py`
- Modify: `backend/agent/state.py`
- Modify: `backend/agent/graph.py`
- Create: `backend/api/coach.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_coach_api.py`
- Test: `backend/tests/test_agent_graph.py`

- [ ] **Step 1: Add failing Coach API test**

Create `backend/tests/test_coach_api.py`:

```python
from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_coach_action_wraps_agent_with_context():
    response = client.post(
        "/coach/action",
        json={"surface": "today", "action": "explain_today", "date": "2026-07-09"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["surface"] == "today"
    assert data["action"] == "explain_today"
    assert data["answer_markdown"]
    assert data["trace"]["surface"] == "today"
```

- [ ] **Step 2: Run the failing test**

```powershell
.\.venv\Scripts\python -m pytest backend\tests\test_coach_api.py -q -p no:cacheprovider
```

Expected: fails with missing `/coach/action`.

- [ ] **Step 3: Add Coach schemas**

In `backend/schemas.py`, add:

```python
CoachSurface = Literal["today", "logbook", "review", "plan", "profile"]
CoachAction = Literal[
    "explain_today",
    "suggest_next_meal",
    "adjust_today_training",
    "explain_weekly_report",
    "adjust_next_plan",
    "suggest_targets",
]


class CoachActionRequest(BaseModel):
    surface: CoachSurface
    action: CoachAction
    date: str | None = None
    question: str | None = Field(default=None, max_length=1000)


class CoachActionResponse(BaseModel):
    surface: CoachSurface
    action: CoachAction
    answer_markdown: str
    intent: str
    trace: dict
    sources: list[dict] = Field(default_factory=list)
```

- [ ] **Step 4: Add Agent context wrapper**

In `backend/agent/state.py`, add optional keys to `AgentState`:

```python
surface: str | None
coach_action: str | None
context_date: str | None
```

In `backend/agent/graph.py`, add:

```python
def run_contextual_coach_action(
    surface: str,
    action: str,
    date: str | None,
    question: str | None = None,
    user_id: str | None = None,
) -> dict:
    prompt = _coach_prompt(surface, action, date, question)
    result = run_fitlife_agent(prompt, user_id)
    result["trace"] = {**result.get("trace", {}), "surface": surface, "coach_action": action, "context_date": date}
    return result


def _coach_prompt(surface: str, action: str, date: str | None, question: str | None) -> str:
    base = {
        "explain_today": "Explain today's calorie, protein, and training status using the user's records.",
        "suggest_next_meal": "Suggest the next meal using today's remaining calorie and protein gap.",
        "adjust_today_training": "Suggest a practical training adjustment for today based on the user's profile and records.",
        "explain_weekly_report": "Explain the weekly report and identify the most important behavior change.",
        "adjust_next_plan": "Adjust the next plan using recent records and the user's profile.",
        "suggest_targets": "Suggest calorie and protein targets from the user's body state, goal, and training frequency.",
    }[action]
    suffix = f" Date: {date}." if date else ""
    user_text = f" User question: {question}" if question else ""
    return f"{base} Surface: {surface}.{suffix}{user_text}"
```

- [ ] **Step 5: Expose `/coach/action`**

Create `backend/api/coach.py`:

```python
from fastapi import APIRouter, Depends

from backend.agent.graph import run_contextual_coach_action
from backend.api.dependencies import optional_current_user
from backend.api.utils import ok
from backend.schemas import AuthenticatedUser, CoachActionRequest


router = APIRouter(prefix="/coach")


@router.post("/action")
def coach_action(request: CoachActionRequest, user: AuthenticatedUser | None = Depends(optional_current_user)):
    result = run_contextual_coach_action(
        surface=request.surface,
        action=request.action,
        date=request.date,
        question=request.question,
        user_id=user.user_id if user else None,
    )
    return ok(
        {
            "surface": request.surface,
            "action": request.action,
            "answer_markdown": result["answer_markdown"],
            "intent": result["intent"],
            "trace": result["trace"],
            "sources": result.get("sources", []),
        }
    )
```

Register it in `backend/main.py`.

- [ ] **Step 6: Run Coach and graph tests**

```powershell
.\.venv\Scripts\python -m pytest backend\tests\test_coach_api.py backend\tests\test_agent_graph.py backend\tests\test_chat_api.py -q -p no:cacheprovider
```

Expected: pass and preserve existing `/chat` behavior.

- [ ] **Step 7: Commit**

```powershell
git add backend\schemas.py backend\agent\state.py backend\agent\graph.py backend\api\coach.py backend\main.py backend\tests\test_coach_api.py backend\tests\test_agent_graph.py
git commit -m "feat: add contextual coach API"
```

---

## Task 4: Frontend Route Hierarchy and Product Shell

**Files:**

- Modify: `frontend/src/routes/AppRoutes.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/styles/index.css`
- Create: `frontend/src/pages/Today.tsx`
- Create: `frontend/src/pages/Logbook.tsx`
- Create: `frontend/src/pages/Review.tsx`

- [ ] **Step 1: Add the new route map**

Update `frontend/src/routes/AppRoutes.tsx` so ordinary routes are:

```tsx
<Route path="/" element={<Today />} />
<Route path="/logbook" element={<Logbook />} />
<Route path="/review" element={<Review />} />
<Route path="/plan" element={<Plan />} />
<Route path="/profile" element={<Profile />} />
<Route path="/records" element={<Navigate to="/logbook" replace />} />
<Route path="/dashboard" element={<Navigate to="/" replace />} />
<Route path="/report" element={<Navigate to="/review" replace />} />
<Route path="/upload" element={<Navigate to="/logbook" replace />} />
<Route path="/chat" element={<Navigate to="/" replace />} />
<Route path="/evaluation" element={<Evaluation />} />
```

Keep `/evaluation` available but remove it from ordinary nav.

- [ ] **Step 2: Replace sidebar items**

In `frontend/src/components/Sidebar.tsx`, use these labels and icons:

```tsx
const items = [
  { to: '/', label: 'Today', icon: CalendarCheck },
  { to: '/logbook', label: 'Logbook', icon: CalendarDays },
  { to: '/review', label: 'Review', icon: BarChart3 },
  { to: '/plan', label: 'Plan', icon: Activity },
  { to: '/profile', label: 'Profile', icon: UserRound },
]
```

Update the product subtitle from `Agentic RAG Coach` to `Daily fitness log`.

- [ ] **Step 3: Create temporary page shells**

Create `Today.tsx`, `Logbook.tsx`, and `Review.tsx` with simple page shells that compile before deeper work:

```tsx
export function Today() {
  return (
    <div className="page-stack">
      <header className="page-header">
        <span>Daily workspace</span>
        <h1>Today</h1>
      </header>
    </div>
  )
}
```

Use equivalent shells for `Logbook` and `Review`.

- [ ] **Step 4: Run frontend build**

```powershell
cd frontend
npm run build
```

Expected: TypeScript and Vite build pass.

- [ ] **Step 5: Commit**

```powershell
git add frontend\src\routes\AppRoutes.tsx frontend\src\components\Sidebar.tsx frontend\src\components\Layout.tsx frontend\src\pages\Today.tsx frontend\src\pages\Logbook.tsx frontend\src\pages\Review.tsx frontend\src\styles\index.css
git commit -m "feat: add today-first navigation"
```

---

## Task 5: Frontend Today Workspace

**Files:**

- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/services/api.ts`
- Create: `frontend/src/hooks/useToday.ts`
- Create: `frontend/src/components/TargetProgress.tsx`
- Create: `frontend/src/components/CoachPanel.tsx`
- Modify: `frontend/src/pages/Today.tsx`
- Modify: `frontend/src/styles/index.css`

- [ ] **Step 1: Add frontend types**

In `frontend/src/types/index.ts`, add:

```ts
export interface TargetProgress {
  label: string
  current: number
  target: number
  unit: string
  remaining: number
  status: 'under' | 'met' | 'over'
}

export interface TodayOverview {
  date: string
  summary: DailySummary
  meals: MealRecord[]
  workouts: WorkoutRecord[]
  targets: TargetProgress[]
  coach_actions: string[]
}

export interface CoachActionRequest {
  surface: 'today' | 'logbook' | 'review' | 'plan' | 'profile'
  action: string
  date?: string
  question?: string
}

export interface CoachActionResponse {
  surface: string
  action: string
  answer_markdown: string
  intent: string
  trace: Record<string, unknown>
  sources: Array<{ source: string; heading?: string; text?: string }>
}
```

- [ ] **Step 2: Add API methods**

In `frontend/src/services/api.ts`, add:

```ts
today: (date: string) => request<TodayOverview>(`/today?date=${encodeURIComponent(date)}`),
coachAction: (payload: CoachActionRequest) =>
  request<CoachActionResponse>('/coach/action', { method: 'POST', body: JSON.stringify(payload) }),
```

- [ ] **Step 3: Add `useToday` hook**

Create `frontend/src/hooks/useToday.ts`:

```ts
import { useEffect, useState } from 'react'

import { api } from '../services/api'
import type { TodayOverview } from '../types'

export function useToday(date: string) {
  const [data, setData] = useState<TodayOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
    setLoading(true)
    setError(null)
    try {
      setData(await api.today(date))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [date])

  return { data, loading, error, refresh }
}
```

- [ ] **Step 4: Build reusable `TargetProgress`**

Create `frontend/src/components/TargetProgress.tsx`:

```tsx
import type { TargetProgress as TargetProgressType } from '../types'

export function TargetProgress({ target }: { target: TargetProgressType }) {
  const ratio = target.target > 0 ? Math.min(1.2, target.current / target.target) : 0
  return (
    <div className={`target-progress ${target.status}`}>
      <div>
        <span>{target.label}</span>
        <strong>{Math.round(target.current)} / {Math.round(target.target)} {target.unit}</strong>
      </div>
      <div className="target-progress-track">
        <span style={{ width: `${Math.min(100, ratio * 100)}%` }} />
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Build `CoachPanel`**

Create `frontend/src/components/CoachPanel.tsx`:

```tsx
import ReactMarkdown from 'react-markdown'

import { api } from '../services/api'
import type { CoachActionResponse } from '../types'
import { useState } from 'react'

interface CoachPanelProps {
  surface: 'today' | 'logbook' | 'review' | 'plan' | 'profile'
  date?: string
  actions: Array<{ action: string; label: string }>
}

export function CoachPanel({ surface, date, actions }: CoachPanelProps) {
  const [answer, setAnswer] = useState<CoachActionResponse | null>(null)
  const [loading, setLoading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function run(action: string) {
    setLoading(action)
    setError(null)
    try {
      setAnswer(await api.coachAction({ surface, action, date }))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(null)
    }
  }

  return (
    <aside className="coach-panel">
      <h2>Coach</h2>
      <div className="coach-actions">
        {actions.map((item) => (
          <button key={item.action} type="button" onClick={() => void run(item.action)} disabled={loading !== null}>
            {loading === item.action ? 'Thinking...' : item.label}
          </button>
        ))}
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      {answer ? <ReactMarkdown>{answer.answer_markdown}</ReactMarkdown> : null}
    </aside>
  )
}
```

- [ ] **Step 6: Compose Today page**

Update `frontend/src/pages/Today.tsx` to:

- load `useToday(selectedDate)`;
- show date picker;
- render `TargetProgress` list;
- render meals and workouts;
- include smart entry and compact meal/workout forms by reusing logic from current `Records.tsx`;
- call `refresh()` after record writes;
- show `CoachPanel` with `explain_today`, `suggest_next_meal`, and `adjust_today_training`.

- [ ] **Step 7: Run frontend build**

```powershell
cd frontend
npm run build
```

Expected: pass.

- [ ] **Step 8: Commit**

```powershell
git add frontend\src\types\index.ts frontend\src\services\api.ts frontend\src\hooks\useToday.ts frontend\src\components\TargetProgress.tsx frontend\src\components\CoachPanel.tsx frontend\src\pages\Today.tsx frontend\src\styles\index.css
git commit -m "feat: build today workspace"
```

---

## Task 6: Logbook, Review, Plan, and Profile Product Pages

**Files:**

- Create or modify: `frontend/src/pages/Logbook.tsx`
- Create or modify: `frontend/src/pages/Review.tsx`
- Modify: `frontend/src/pages/Plan.tsx`
- Modify: `frontend/src/pages/Profile.tsx`
- Modify: `frontend/src/components/ProfileForm.tsx`
- Modify: `frontend/src/styles/index.css`

- [ ] **Step 1: Convert Records into Logbook**

Move the historical calendar, day detail, and CSV import from `Records.tsx` into `Logbook.tsx`.

Keep these responsibilities in Logbook:

- rolling calendar;
- selected-day details;
- full meal/workout forms;
- CSV import.

Remove Today-only language such as "Daily records" if the section is now historical.

- [ ] **Step 2: Build Review from trends and report**

In `Review.tsx`, combine:

- trend charts from current `Dashboard.tsx`;
- weekly report generation from current `WeeklyReport.tsx`;
- `CoachPanel` action `explain_weekly_report`.

Use `/dashboard/summary` for trends and `/report/weekly` for report generation.

- [ ] **Step 3: Upgrade Plan page**

In `Plan.tsx`:

- keep `/plan/generate`;
- render validation status near the top;
- show diet and workout plan as separate work sections;
- add `CoachPanel` action `adjust_next_plan`;
- change copy from "Generate diet and training plan" to "Plan".

- [ ] **Step 4: Upgrade Profile page**

In `Profile.tsx` and `ProfileForm.tsx`:

- add experience level selector;
- add training preference selector;
- add target mode selector;
- remove prominent diet-preference language if still visible;
- keep allergies/restrictions/foods-not-eaten;
- show suggested target rationale when backend exposes it in a later task.

- [ ] **Step 5: Run build**

```powershell
cd frontend
npm run build
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add frontend\src\pages\Logbook.tsx frontend\src\pages\Review.tsx frontend\src\pages\Plan.tsx frontend\src\pages\Profile.tsx frontend\src\components\ProfileForm.tsx frontend\src\styles\index.css
git commit -m "feat: productize logbook review plan and profile"
```

---

## Task 7: Developer Boundary and Documentation

**Files:**

- Modify: `frontend/src/routes/AppRoutes.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `README.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`

- [ ] **Step 1: Keep Evaluation out of ordinary navigation**

Ensure `Sidebar.tsx` has no Evaluation, Upload, Trace, or Chat items.

Keep `/evaluation` route available for direct developer access.

- [ ] **Step 2: Document the new product flow**

In `README.md`, update the user flow to:

1. Register or log in.
2. Complete Profile.
3. Open Today.
4. Record meal/workout by form or smart entry.
5. Review weekly trends and report.
6. Generate and validate the next plan.
7. Use developer Evaluation separately.

- [ ] **Step 3: Update implementation status**

In `docs/IMPLEMENTATION_STATUS.md`, add a v0.2 section:

```markdown
## v0.2 Product Navigation

- Today-first authenticated home page.
- Logbook owns calendar history and CSV import.
- Review owns trends and weekly report generation.
- Plan owns plan generation, validation, and adjustment.
- Profile owns personalization fields and target mode.
- Evaluation remains available as a developer route.
```

- [ ] **Step 4: Run full verification**

```powershell
.\.venv\Scripts\python -m pytest backend\tests -q -p no:cacheprovider
cd frontend
npm run build
```

Expected: backend tests pass, frontend build passes.

- [ ] **Step 5: Commit**

```powershell
git add frontend\src\routes\AppRoutes.tsx frontend\src\components\Sidebar.tsx README.md docs\IMPLEMENTATION_STATUS.md
git commit -m "docs: document today-first product flow"
```

---

## Phase Boundary

This first implementation version intentionally does not include:

- barcode scanning;
- image-based food logging;
- real SMS/email verification;
- wearable imports;
- persistent multi-week plan execution tracking;
- full CRUD editing for every record;
- a production database migration.

Those are valid future features, but they would distract from the immediate productization goal.

## Verification Checklist

- [ ] `GET /today?date=YYYY-MM-DD` returns daily summary, records, targets, and Coach actions.
- [ ] `POST /coach/action` returns a contextual Agent answer and trace metadata.
- [ ] `/` opens Today.
- [ ] `/logbook` opens historical records and CSV import.
- [ ] `/review` opens trends and weekly report.
- [ ] `/plan` opens plan workspace.
- [ ] `/profile` includes personalization fields.
- [ ] Ordinary nav excludes Upload, Evaluation, Trace, and Chat.
- [ ] Legacy routes redirect or are developer-only.
- [ ] Backend tests pass.
- [ ] Frontend build passes.

## Self-Review

- Spec coverage: Covers Today, Logbook, Review, Plan, Profile, contextual Agent surfaces, developer boundary, route redirects, and backend reuse.
- Scope check: This is still large, but it is one coherent productization task because the backend additions are thin orchestration layers and the frontend work is a route/page reorganization around the same data model. If execution feels too large, split after Task 3: backend product contracts first, frontend product pages second.
- Placeholder scan: No unfinished placeholder markers remain.
- Type consistency: Backend `TodayOverview`, `TargetProgress`, `CoachActionRequest`, and `CoachActionResponse` map directly to frontend types.
