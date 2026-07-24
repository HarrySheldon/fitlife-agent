# Food Catalog And Meal Drafts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let authenticated users search a local food catalog, create complete custom foods, build a server-backed multi-item meal draft, and atomically confirm one meal without any model dependency.

**Architecture:** Keep the feature inside the existing modular monolith. Deterministic nutrition conversion lives in the domain layer, catalog and meal persistence use separate ports and SQLite adapters, application services own authorization-independent business rules, and `/api/v1` routes own authentication and request translation. The frontend gets a dedicated `/today/meal/new` task page; Today only links into the workflow.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite/FTS5, React 19, TypeScript, React Router, Vitest, pytest

---

## Scope And Open-Source Practice

The approved source specification is
`docs/superpowers/specs/2026-07-19-today-nutrition-training-records-design.md`.
This plan follows practices verified against:

- [Open Food Facts](https://github.com/openfoodfacts/openfoodfacts-server): keep source identity, attribution, license and per-basis nutrient values separate from user-owned data; do not copy AGPL server code.
- [USDA APIs](https://github.com/USDA/USDA-APIs) and [FoodData Central](https://fdc.nal.usda.gov/api-guide): use public-domain food facts as immutable source records and preserve source IDs.
- [Grocy](https://github.com/grocy/grocy): keep product/catalog identity separate from transactional usage records and snapshot values into historical records.

Phase 3 applies these decisions:

- Runtime search is local-only. External APIs are not called by user requests.
- Public and private foods share one read model but retain ownership and provenance.
- Confirmed meal items snapshot name, amount, unit, four nutrients and source.
- Drafts never affect summaries and use optimistic locking.
- Confirmation is one SQLite transaction and supports `Idempotency-Key`.
- Agent analysis, workout entry, Today SQLite aggregation and catalog import tooling remain in later phases.
- Existing legacy export is not expanded.

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/domain/meals.py` | Food basis validation, deterministic quantity conversion and meal draft invariants |
| `backend/application/ports/food_catalog_repository.py` | Catalog search and custom-food persistence contract |
| `backend/application/ports/meal_repository.py` | Draft lifecycle and atomic confirmation contract |
| `backend/application/use_cases/food_catalog.py` | Search and custom-food orchestration |
| `backend/application/use_cases/meals.py` | Draft create/update/confirm orchestration |
| `backend/infrastructure/repositories/sqlite_food_catalog_repository.py` | FTS5 search, visibility, favorites/recent ranking and custom foods |
| `backend/infrastructure/repositories/sqlite_meal_repository.py` | Optimistic drafts, idempotent confirmation and meal snapshots |
| `backend/api/meal_schemas.py` | Focused catalog and meal request schemas |
| `backend/api/food_catalog.py` | Authenticated `/api/v1/catalog/foods` routes |
| `backend/api/meals.py` | Authenticated `/api/v1/meal-drafts` routes |
| `backend/data/catalog/foods.zh-CN.v1.json` | Small audited local catalog with source/license metadata |
| `backend/infrastructure/catalog/seed_foods.py` | Idempotent bundled-catalog loader and FTS index writer |
| `backend/main.py` | Register routes and seed the bundled catalog after migrations |
| `frontend/src/types/meals.ts` | Focused catalog, draft and confirmed-meal types |
| `frontend/src/services/mealApi.ts` | Phase 3 API client |
| `frontend/src/hooks/useMealDraft.ts` | Draft state, optimistic version and recoverable saves |
| `frontend/src/pages/MealEntry.tsx` | Dedicated catalog-first multi-item meal workflow |
| `frontend/src/routes/AppRoutes.tsx` | `/today/meal/new` route |
| `frontend/src/pages/Today.tsx` | Replace inline meal form with route entry |
| `frontend/src/i18n/resources/*.ts` | Chinese and English meal workflow text |
| `frontend/src/styles/index.css` | Responsive task-page layout |

### Task 1: Deterministic Nutrition Domain

**Files:**
- Create: `backend/domain/meals.py`
- Create: `backend/tests/domain/test_meals.py`

- [x] **Step 1: Write failing quantity-conversion tests**

Cover per-100g, per-100ml and per-serving conversion, one-decimal output, positive amounts, complete custom nutrients and immutable snapshots:

```python
def test_food_portion_scales_per_100g_nutrients():
    food = FoodDefinition(
        name="Cooked rice",
        basis_type="per_100g",
        basis_amount=100,
        unit="g",
        calories=116,
        carbs=25.9,
        protein=2.6,
        fat=0.3,
        source="public",
    )

    portion = portion_from_food(food, amount=150, unit="g")

    assert portion.calories == 174.0
    assert portion.carbs == 38.9
    assert portion.protein == 3.9
    assert portion.fat == 0.5
```

- [x] **Step 2: Run the domain test and verify RED**

Run:

```powershell
docker run --rm --volume "${PWD}\backend:/app/backend" --workdir /app profile-daily-targets-backend python -m pytest backend/tests/domain/test_meals.py
```

Expected: import failure because `backend.domain.meals` does not exist.

- [x] **Step 3: Implement immutable domain values**

Use frozen dataclasses, `Decimal(str(value))`, `ROUND_HALF_UP`, explicit compatible units, and stable error codes:

```python
class MealDomainError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class FoodDefinition:
    name: str
    basis_type: Literal["per_100g", "per_100ml", "per_serving"]
    basis_amount: float
    unit: str
    calories: float
    carbs: float
    protein: float
    fat: float
    source: Literal["public", "user_custom", "agent_estimate", "legacy_import"]


@dataclass(frozen=True)
class FoodPortion:
    food_name: str
    amount: float
    unit: str
    basis_type: Literal["per_100g", "per_100ml", "per_serving"]
    calories: float
    carbs: float
    protein: float
    fat: float
    source: Literal["public", "user_custom", "agent_estimate", "legacy_import"]


def portion_from_food(food: FoodDefinition, *, amount: float, unit: str) -> FoodPortion:
    validate_compatible_unit(food, unit)
    factor = Decimal(str(amount)) / Decimal(str(food.basis_amount))
    return FoodPortion(
        food_name=food.name,
        amount=amount,
        unit=unit,
        basis_type=food.basis_type,
        calories=_scaled(food.calories, factor),
        carbs=_scaled(food.carbs, factor),
        protein=_scaled(food.protein, factor),
        fat=_scaled(food.fat, factor),
        source=food.source,
    )
```

- [x] **Step 4: Run the domain tests and verify GREEN**

Expected: all `backend/tests/domain/test_meals.py` tests pass.

- [x] **Step 5: Commit**

```powershell
git add backend/domain/meals.py backend/tests/domain/test_meals.py
git commit -m "feat: calculate deterministic food portions"
```

### Task 2: Local Food Catalog And Bundled Seed

**Files:**
- Create: `backend/application/ports/food_catalog_repository.py`
- Create: `backend/application/use_cases/food_catalog.py`
- Create: `backend/infrastructure/repositories/sqlite_food_catalog_repository.py`
- Create: `backend/infrastructure/catalog/__init__.py`
- Create: `backend/infrastructure/catalog/seed_foods.py`
- Create: `backend/data/catalog/foods.zh-CN.v1.json`
- Create: `backend/tests/infrastructure/test_sqlite_food_catalog_repository.py`
- Create: `backend/tests/infrastructure/test_food_catalog_seed.py`

- [x] **Step 1: Write failing catalog tests**

Prove:

- public foods are visible to every authenticated user;
- private foods are visible only to their owner;
- inactive records are excluded;
- search matches names and aliases through FTS5;
- ordering is recent use, favorite, private, then public;
- creating a custom food requires four nutrients and creates searchable aliases;
- repeated bundled seed runs are idempotent and retain license/source metadata.

```python
def test_search_foods_ranks_recent_favorite_private_and_public(tmp_path):
    repository = seeded_repository(tmp_path)
    repository.create_custom_food("user-a", custom_food("My rice"))
    repository.set_favorite("user-a", "public-rice", True)
    repository.record_usage("user-a", "public-oats")

    results = repository.search("user-a", "rice oats", limit=20)

    assert [item.rank_group for item in results] == sorted(
        item.rank_group for item in results
    )
    assert all(item.owner_user_id in (None, "user-a") for item in results)
```

- [x] **Step 2: Run catalog tests and verify RED**

Expected: imports fail because the catalog port and adapter do not exist.

- [x] **Step 3: Implement the catalog port, service and SQLite adapter**

Use parameterized SQL and a sanitized prefix query:

```python
def _fts_query(text: str) -> str:
    tokens = re.findall(r"[\w\u3400-\u9fff]+", unicodedata.normalize("NFKC", text))
    return " AND ".join(f'"{token.replace(chr(34), "")}"*' for token in tokens[:8])
```

The adapter must always apply:

```sql
WHERE food.active = 1
  AND (food.owner_user_id IS NULL OR food.owner_user_id = ?)
```

and return source/license/attribution without exposing another user's private rows.

- [x] **Step 4: Add the bundled audited catalog**

Add a small, reviewable first dataset of common staple foods. Every JSON record must include:

```json
{
  "source_name": "USDA FoodData Central",
  "source_record_id": "169756",
  "dataset_version": "2026-07-24",
  "license": "CC0-1.0",
  "attribution": "USDA FoodData Central",
  "basis_type": "per_100g",
  "basis_amount": 100,
  "unit": "g",
  "calories": 365,
  "carbs": 79.95,
  "protein": 7.13,
  "fat": 0.66,
  "aliases": ["大米", "白米", "raw white rice", "dami"]
}
```

The loader hashes canonical source JSON, upserts by `(source_name, source_record_id)`, and rebuilds only affected FTS rows.

- [x] **Step 5: Run catalog, schema and lifecycle tests**

Run the focused repository tests plus account-deletion tests. Expected: all pass and no account-export manifest changes.

- [x] **Step 6: Commit**

```powershell
git add backend/application/ports/food_catalog_repository.py backend/application/use_cases/food_catalog.py backend/infrastructure/repositories/sqlite_food_catalog_repository.py backend/infrastructure/catalog backend/data/catalog backend/tests/infrastructure
git commit -m "feat: add local searchable food catalog"
```

### Task 3: Versioned Meal Drafts And Atomic Confirmation

**Files:**
- Create: `backend/application/ports/meal_repository.py`
- Create: `backend/application/use_cases/meals.py`
- Create: `backend/infrastructure/repositories/sqlite_meal_repository.py`
- Create: `backend/tests/application/test_meals.py`
- Create: `backend/tests/infrastructure/test_sqlite_meal_repository.py`

- [x] **Step 1: Write failing draft tests**

Cover create/get/update/delete, owner isolation, 30-day expiry, stale-version `409`, incomplete-item rejection, catalog snapshot stability, custom-food confirmation, idempotent retries and all-or-nothing rollback.

```python
def test_confirm_draft_atomically_creates_meal_items_and_usage(tmp_path):
    repository = meal_repository(tmp_path)
    draft = repository.create_draft("user-a", complete_two_item_payload(), expires_at)

    confirmed = repository.confirm(
        "user-a",
        draft.id,
        expected_version=draft.version,
        idempotency_key="confirm-1",
        request_fingerprint="fingerprint-1",
    )

    assert len(confirmed.items) == 2
    assert repository.get_draft("user-a", draft.id) is None
    assert repository.list_meals("user-a", confirmed.log_date) == (confirmed,)
```

- [x] **Step 2: Run draft tests and verify RED**

Expected: imports fail because the meal repository does not exist.

- [x] **Step 3: Implement optimistic drafts**

`PATCH` persistence must execute:

```sql
UPDATE record_drafts
SET payload_json = ?, version = version + 1, updated_at = ?
WHERE id = ? AND user_id = ? AND version = ? AND expires_at > ?
```

Zero updated rows are resolved into `DRAFT_NOT_FOUND`, `DRAFT_EXPIRED` or `DRAFT_VERSION_CONFLICT`.

- [x] **Step 4: Implement atomic idempotent confirmation**

Inside one `BEGIN IMMEDIATE` transaction:

1. replay a matching idempotency response;
2. load and validate the owned unexpired draft/version;
3. create or resolve `daily_logs`;
4. allocate the meal position;
5. insert the meal and all snapshot items;
6. upsert catalog usage;
7. optionally create complete user-custom foods;
8. save the idempotency response;
9. delete the draft.

Any failure rolls back all nine operations.

- [x] **Step 5: Run repository, service and lifecycle tests**

Expected: all focused tests pass, including concurrent retries and account deletion.

- [x] **Step 6: Commit**

```powershell
git add backend/application/ports/meal_repository.py backend/application/use_cases/meals.py backend/infrastructure/repositories/sqlite_meal_repository.py backend/tests/application/test_meals.py backend/tests/infrastructure/test_sqlite_meal_repository.py
git commit -m "feat: confirm meal drafts atomically"
```

### Task 4: Authenticated Phase 3 API

**Files:**
- Create: `backend/api/meal_schemas.py`
- Create: `backend/api/food_catalog.py`
- Create: `backend/api/meals.py`
- Modify: `backend/main.py`
- Modify: `backend/i18n.py`
- Create: `backend/tests/test_food_catalog_api.py`
- Create: `backend/tests/test_meal_drafts_api.py`

- [x] **Step 1: Write failing API contract tests**

Required endpoints:

```text
GET    /api/v1/catalog/foods/search?q=&limit=
POST   /api/v1/catalog/foods/custom
PUT    /api/v1/catalog/foods/{food_id}/favorite
DELETE /api/v1/catalog/foods/{food_id}/favorite
POST   /api/v1/meal-drafts
GET    /api/v1/meal-drafts/{draft_id}
PATCH  /api/v1/meal-drafts/{draft_id}
DELETE /api/v1/meal-drafts/{draft_id}
POST   /api/v1/meal-drafts/{draft_id}/confirm
```

All routes require authentication. Confirm requires `Idempotency-Key` and `If-Match` draft version. Tests cover localized `401`, `404`, `409` and `422` responses.

- [x] **Step 2: Run API tests and verify RED**

Expected: `404` because routes are not registered.

- [x] **Step 3: Implement focused Pydantic schemas and routes**

Keep route handlers thin:

```python
@router.patch("/meal-drafts/{draft_id}")
def update_draft(
    draft_id: str,
    payload: MealDraftUpdateRequest,
    if_match: int = Header(alias="If-Match"),
    user: AuthenticatedUser = Depends(require_current_user),
    service: MealService = Depends(get_meal_service),
):
    return ok(
        asdict(service.update_draft(user.user_id, draft_id, if_match, payload)),
        processing_mode="deterministic",
    )
```

Wrap mutations with the existing user lifecycle guard.

- [x] **Step 4: Run API, auth and legacy regressions**

Expected: API tests pass and legacy `/calendar/meals` remains unchanged until the Phase 6 cutover.

- [x] **Step 5: Commit**

```powershell
git add backend/api/meal_schemas.py backend/api/food_catalog.py backend/api/meals.py backend/main.py backend/i18n.py backend/tests/test_food_catalog_api.py backend/tests/test_meal_drafts_api.py
git commit -m "feat: expose meal draft workflow"
```

### Task 5: Frontend Meal Client And Draft State

**Files:**
- Create: `frontend/src/types/meals.ts`
- Create: `frontend/src/services/mealApi.ts`
- Create: `frontend/src/services/mealApi.test.ts`
- Create: `frontend/src/hooks/useMealDraft.ts`
- Create: `frontend/src/hooks/useMealDraft.test.tsx`

- [x] **Step 1: Write failing client and hook tests**

Prove authorization/language headers reuse the shared request boundary, search parameters are encoded, updates send `If-Match`, confirms send both concurrency headers, and stale saves retain local form values.

- [x] **Step 2: Run focused frontend tests and verify RED**

Expected: imports fail because the focused meal modules do not exist.

- [x] **Step 3: Implement the focused API client**

Expose narrow methods:

```typescript
export const mealApi = {
  searchFoods(query: string, limit = 20): Promise<FoodSearchResult[]>,
  createCustomFood(input: CustomFoodInput): Promise<FoodCatalogItem>,
  createDraft(input: MealDraftCreate): Promise<MealDraft>,
  updateDraft(id: string, version: number, input: MealDraftUpdate): Promise<MealDraft>,
  confirmDraft(id: string, version: number, idempotencyKey: string): Promise<ConfirmedMeal>,
}
```

- [x] **Step 4: Implement recoverable draft state**

The hook owns remote version, save state and retry. A `409` sets `conflict` without discarding local items. No Agent call exists in this phase.

- [x] **Step 5: Run focused tests and commit**

```powershell
git add frontend/src/types/meals.ts frontend/src/services/mealApi.ts frontend/src/services/mealApi.test.ts frontend/src/hooks/useMealDraft.ts frontend/src/hooks/useMealDraft.test.tsx
git commit -m "feat: add meal draft client state"
```

### Task 6: Dedicated Meal Entry Page

**Files:**
- Create: `frontend/src/pages/MealEntry.tsx`
- Create: `frontend/src/pages/MealEntry.test.tsx`
- Modify: `frontend/src/routes/AppRoutes.tsx`
- Modify: `frontend/src/pages/Today.tsx`
- Modify: `frontend/src/i18n/resources/en-US.ts`
- Modify: `frontend/src/i18n/resources/zh-CN.ts`
- Modify: `frontend/src/i18n/trackedStrings.test.ts`
- Modify: `frontend/src/styles/index.css`

- [ ] **Step 1: Write failing interaction tests**

Cover:

- dedicated route renders instead of an inline Today meal form;
- search results show food, basis, calories and four nutrients;
- selecting a food requires an explicit positive amount;
- two foods can be added to one draft;
- numeric fields start empty;
- a no-result path opens complete custom-food fields;
- incomplete custom food cannot become confirmed data;
- confirmation is disabled while saving and redirects only after success;
- `409` shows recovery without clearing inputs.

- [ ] **Step 2: Run interaction tests and verify RED**

Expected: route falls through to Today and `MealEntry` is missing.

- [ ] **Step 3: Implement the task page**

Use an unframed two-column desktop layout and one-column mobile layout:

```text
Header: back, date, meal name
Left: search, source filters, compact result list, custom-food form
Right: selected items, amount controls, nutrient totals, save state, confirm
```

Do not nest cards. Use icon buttons for remove/favorite and tooltips for unfamiliar icons. Keep the primary confirm command visible without overlaying content.

- [ ] **Step 4: Replace the Today inline meal form**

The Today meal action navigates to:

```text
/today/meal/new?date=YYYY-MM-DD
```

Smart entry and workout behavior remain unchanged until their phases.

- [ ] **Step 5: Run frontend tests and production build**

Run the complete Vitest suite and `npm run build`. Expected: all pass; only the existing bundle-size warning may remain.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/pages/MealEntry.tsx frontend/src/pages/MealEntry.test.tsx frontend/src/routes/AppRoutes.tsx frontend/src/pages/Today.tsx frontend/src/i18n frontend/src/styles/index.css
git commit -m "feat: build catalog-first meal entry"
```

### Task 7: Phase 3 Integration And Acceptance

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-07-19-today-records-program-roadmap.md`
- Modify: `docs/superpowers/plans/2026-07-24-food-catalog-meal-drafts.md`

- [ ] **Step 1: Run complete backend verification**

Expected: every backend test passes with only documented warnings.

- [ ] **Step 2: Run complete frontend verification and build**

Expected: every frontend test and the production build pass.

- [ ] **Step 3: Rebuild Docker and verify health**

```powershell
docker compose config --quiet
docker compose up --build -d
curl.exe --fail http://127.0.0.1:8000/health
```

- [ ] **Step 4: Perform browser acceptance**

Desktop and `390x844` mobile:

1. sign in with an existing completed-onboarding account;
2. open `/today/meal/new`;
3. search the bundled catalog;
4. add two foods with quantities;
5. create one complete custom food;
6. confirm the meal;
7. verify success and no duplicate after retry/reload;
8. verify no horizontal overflow or console errors.

- [ ] **Step 5: Review and harden**

Request a read-only final review focused on authorization, FTS query safety, optimistic locking, idempotency, transaction rollback, historical snapshots, account deletion and the excluded export boundary. Fix every Critical or Important finding and rerun affected verification.

- [ ] **Step 6: Mark Phase 3 complete and commit**

Update evidence with real counts and timings only after verification.

```powershell
git add README.md docs/superpowers/plans
git commit -m "docs: verify food catalog and meal drafts"
```

- [ ] **Step 7: Push the clean branch**

Push `codex/food-catalog-meal-drafts`, verify local and remote SHAs match, then begin the Phase 4 design-to-plan cycle from this commit.

## Completion Criteria

- Catalog search is local, ownership-safe and source-aware.
- Custom foods require calories, carbohydrates, protein and fat.
- Multi-item meal drafts survive recoverable save failures.
- Draft versions reject stale updates with `409`.
- Confirmation is idempotent and atomic.
- Confirmed items retain nutrition and provenance snapshots.
- No Agent call is required or available in this workflow.
- Existing legacy APIs remain functional until the documented cutover.
- Backend, frontend, production build, Docker and desktop/mobile acceptance pass.
