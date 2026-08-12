# Mainland Catalog Localization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace English and Taiwan-region public catalog display text with reviewed Mainland Chinese text while preserving stable IDs, source provenance, aliases, transactional imports, and historical snapshots.

**Architecture:** Add a deterministic localization loader between source projection and canonical record construction. Every food name receives the OpenCC `tw2sp` baseline, versioned structured glossary rules apply broadly, and the food entry map remains a sparse set of ID-specific contextual or collision overrides plus review metadata. Foods do not require exact ID coverage. Exercises require a complete ID-keyed static translation overlay plus a shared taxonomy dictionary. The existing seed payloads, SQLite tables, import ledger, FTS index, API contracts, and React components remain the runtime path.

**Tech Stack:** Python 3.12, Pydantic 2, OpenCC, FastAPI, SQLite/FTS5, pytest, React/TypeScript/Vitest, Docker Compose.

---

## File Map

**Create**

- `backend/catalog_receiver/localization.py`: strict localization models, JSON loading, sparse food override validation, exact exercise ID coverage, collision, residual-Latin, taxonomy, and alias validation.
- `backend/data/catalog/localizations/tfda-foods.zh-CN.v1.json`: Mainland food glossary and ID-specific reviewed overrides.
- `backend/data/catalog/localizations/free-exercise-db.zh-CN.v2.json`: complete 750-ID exercise names, aliases, and translated instructions.
- `backend/data/catalog/localizations/exercise-taxonomy.zh-CN.v1.json`: shared muscle, equipment, level, mechanic, force, and category terms plus approved abbreviations.
- `backend/tests/catalog_receiver/test_localization.py`: isolated localization contract and failure tests.
- `backend/tests/catalog_receiver/fixtures/food-localization.zh-CN.json`: minimal food localization fixture.
- `backend/tests/catalog_receiver/fixtures/exercise-localization.zh-CN.json`: minimal exercise localization fixture.
- `backend/tests/catalog_receiver/fixtures/exercise-taxonomy.zh-CN.json`: minimal taxonomy fixture.
- `scripts/build_localized_catalogs.py`: deterministic bundled-catalog localization and atomic JSON output.
- `backend/tests/catalog_receiver/test_build_localized_catalogs.py`: build command, idempotence, and blocked-output tests.

**Modify**

- `backend/catalog_receiver/models.py`: add `opencc_tw2sp` and localization path configuration.
- `backend/catalog_receiver/mapping.py`: construct and execute the OpenCC `tw2sp` converter.
- `backend/catalog_receiver/projectors.py`: apply food and exercise localization without English fallback.
- `backend/catalog_receiver/validators.py`: add stable localization issue messages and catalog-wide display validation.
- `backend/catalog_receiver/service.py`: load localization assets once and pass them to projection and validation.
- `backend/tools/catalog_receiver.py`: expose repeatable `--localization` and `--taxonomy` options.
- `scripts/import_initial_catalogs.py`: require food, exercise, and taxonomy localization assets during initial imports.
- `backend/data/catalog/mappings/tfda-foods.v1.json`: use `opencc_tw2sp` and raise the profile version.
- `backend/data/catalog/mappings/free-exercise-db.v1.json`: require full localization coverage and raise the profile version.
- `backend/data/catalog/foods.zh-CN.v1.json`: regenerate Mainland canonical names while preserving aliases and source metadata.
- `backend/data/catalog/exercises.zh-CN.v1.json`: regenerate Chinese names, taxonomy, and instructions while preserving upstream provenance.
- `backend/tests/catalog_receiver/test_mapping.py`: cover `tw2sp`.
- `backend/tests/catalog_receiver/test_tfda_projector.py`: assert Mainland name and source aliases.
- `backend/tests/catalog_receiver/test_exercise_projector.py`: assert strict localized fields and no fallback.
- `backend/tests/catalog_receiver/test_service.py`: assert localization failures block imports.
- `backend/tests/catalog_receiver/test_cli.py`: cover localization arguments and coded failures.
- `backend/tests/catalog_receiver/test_initial_import_script.py`: cover validate-both-before-write with all localization assets.
- `backend/tests/catalog_receiver/test_real_data_acceptance.py`: audit all production food names through baseline, glossary, and sparse overrides; assert complete exercise coverage and no unapproved Latin text.
- `backend/tests/infrastructure/test_food_catalog_seed.py`: assert reimport updates names without changing IDs.
- `backend/tests/infrastructure/test_exercise_catalog_seed.py`: assert translated provenance and alias indexing.
- `backend/tests/test_food_catalog_api.py`: assert Mainland display name and Taiwan/English alias search.
- `backend/tests/test_workout_drafts_api.py`: assert Mainland exercise display and English alias search.
- `frontend/src/components/meals/FoodCatalogPane.test.tsx`: assert Mainland food results render unchanged through the API contract.
- `frontend/src/components/workouts/ExerciseCatalogPane.test.tsx`: assert Mainland exercise and muscle text render.
- `README.md`: document localization assets, regeneration, validation, and runtime Agent boundary.

## Task 1: Localization Contracts And Loader

**Files:**
- Create: `backend/catalog_receiver/localization.py`
- Create: `backend/tests/catalog_receiver/test_localization.py`
- Create: `backend/tests/catalog_receiver/fixtures/food-localization.zh-CN.json`
- Create: `backend/tests/catalog_receiver/fixtures/exercise-localization.zh-CN.json`
- Create: `backend/tests/catalog_receiver/fixtures/exercise-taxonomy.zh-CN.json`

- [ ] **Step 1: Write failing loader contract tests**

Cover valid food and exercise assets, duplicate JSON keys, wrong source name, sparse food entries, food orphan IDs, exercise missing/orphan IDs, instruction-count mismatch, duplicate canonical names, canonical-name aliases, and unapproved Latin text. Use explicit assertions such as:

```python
bundle = load_localization_bundle(
    catalog_kind="exercise",
    localization_path=EXERCISE_LOCALIZATION,
    taxonomy_path=EXERCISE_TAXONOMY,
)
localized = bundle.exercise("Barbell_Full_Squat", instruction_count=2)
assert localized.name_zh_cn == "杠铃深蹲"
assert localized.instructions_zh_cn == ("将杠铃置于上背部。", "屈髋屈膝下蹲。")
```

- [ ] **Step 2: Verify the tests fail for the missing module**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/catalog_receiver/test_localization.py -q`

Expected: collection fails with `ModuleNotFoundError: backend.catalog_receiver.localization`.

- [ ] **Step 3: Implement strict Pydantic models and loader**

Define `FoodLocalizationAsset`, `ExerciseLocalizationAsset`, `ExerciseTaxonomyAsset`, `FoodLocalizationEntry`, `ExerciseLocalizationEntry`, and an immutable `LocalizationBundle`. Load JSON with an `object_pairs_hook` that rejects duplicate keys. Normalize aliases with NFKC/casefold, but preserve the authored display string.

Expose these interfaces:

```python
def load_localization_bundle(
    *,
    catalog_kind: CatalogKind,
    localization_path: str | Path,
    taxonomy_path: str | Path | None = None,
) -> LocalizationBundle: ...

def validate_localization_coverage(
    bundle: LocalizationBundle,
    source_ids: set[str],
) -> tuple[ReceiverIssue, ...]: ...
```

Use stable error codes: `LOCALIZATION_INVALID`, `LOCALIZATION_MISSING`, `LOCALIZATION_ORPHAN`, `LOCALIZATION_INSTRUCTION_COUNT_MISMATCH`, `LOCALIZATION_NAME_COLLISION`, `LOCALIZATION_LATIN_UNAPPROVED`, and `LOCALIZATION_ALIAS_REDUNDANT`.

- [ ] **Step 4: Run the focused tests**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/catalog_receiver/test_localization.py -q`

Expected: all localization loader tests pass.

- [ ] **Step 5: Commit the contract slice**

```powershell
git add backend/catalog_receiver/localization.py backend/tests/catalog_receiver/test_localization.py backend/tests/catalog_receiver/fixtures/food-localization.zh-CN.json backend/tests/catalog_receiver/fixtures/exercise-localization.zh-CN.json backend/tests/catalog_receiver/fixtures/exercise-taxonomy.zh-CN.json
git commit -m "feat: define catalog localization contracts"
```

## Task 2: Taiwan-To-Mainland Food Projection

**Files:**
- Modify: `backend/catalog_receiver/models.py`
- Modify: `backend/catalog_receiver/mapping.py`
- Modify: `backend/catalog_receiver/projectors.py`
- Modify: `backend/catalog_receiver/validators.py`
- Modify: `backend/data/catalog/mappings/tfda-foods.v1.json`
- Create: `backend/data/catalog/localizations/tfda-foods.zh-CN.v1.json`
- Modify: `backend/tests/catalog_receiver/test_mapping.py`
- Modify: `backend/tests/catalog_receiver/test_tfda_projector.py`

- [ ] **Step 1: Write failing food conversion and precedence tests**

Assert `apply_transform("白飯", TransformSpec(operation="opencc_tw2sp")) == "白饭"`, matching the installed generic OpenCC converter. Separately assert that the food projector plus the versioned localization asset applies `白饭 -> 米饭`. Add projector cases proving the precedence `record override > glossary > tw2sp`, and verify `白飯`, `白饭`, `米飯`, and `Cooked rice` remain aliases while `米饭` is canonical. This documents the approved separation between generic OpenCC conversion and project-owned food terminology; it is not a relaxation of the canonical-name requirement.

- [ ] **Step 2: Run the food tests and confirm the missing transform fails**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/catalog_receiver/test_mapping.py backend/tests/catalog_receiver/test_tfda_projector.py -q`

Expected: failure because `opencc_tw2sp` and food localization are not implemented.

- [ ] **Step 3: Add the transform and localize grouped food records**

Add `opencc_tw2sp` to `TransformOperation`, create `OpenCC("tw2sp")`, and update the TFDA profile to `profile_version: 2.0.0`. In `_project_foods`, apply `tw2sp` to every food, select at most one structured glossary rule without cascading, then apply a reviewed sparse localization entry by stable source ID only when present. Merge upstream names into aliases and record this provenance:

```python
"localization": {
    "locale": "zh-CN",
    "asset_version": bundle.version,
    "upstream_name": traditional_name,
    "method": localized.method,
}
```

- [ ] **Step 4: Author the food glossary and reviewed ID overrides**

Populate the versioned asset with Mainland terms including `白饭 -> 米饭`, `鲔鱼 -> 金枪鱼`, `马铃薯 -> 土豆`, `青花菜 -> 西兰花`, `奇异果 -> 猕猴桃`, and `凤梨 -> 菠萝`. Structured rules carry explicit unique integer priorities so equal-specificity selection never depends on JSON order. Add ID-specific entries only when the phrase rule would change meaning or create a collision. Every sparse override must include a non-empty `review_note`; do not add one entry per food.

- [ ] **Step 5: Run focused food tests**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/catalog_receiver/test_mapping.py backend/tests/catalog_receiver/test_tfda_projector.py backend/tests/catalog_receiver/test_localization.py -q`

Expected: all tests pass; the fixture canonical name is `米饭` and old names remain aliases.

- [ ] **Step 6: Commit the food projection slice**

```powershell
git add backend/catalog_receiver/models.py backend/catalog_receiver/mapping.py backend/catalog_receiver/projectors.py backend/catalog_receiver/validators.py backend/data/catalog/mappings/tfda-foods.v1.json backend/data/catalog/localizations/tfda-foods.zh-CN.v1.json backend/tests/catalog_receiver
git commit -m "feat: localize Taiwan food names for Mainland users"
```

## Task 3: Strict Exercise Localization Projection

**Files:**
- Modify: `backend/catalog_receiver/projectors.py`
- Modify: `backend/catalog_receiver/validators.py`
- Modify: `backend/data/catalog/mappings/free-exercise-db.v1.json`
- Create: `backend/data/catalog/localizations/exercise-taxonomy.zh-CN.v1.json`
- Modify: `backend/tests/catalog_receiver/test_exercise_projector.py`
- Modify: `backend/tests/catalog_receiver/test_service.py`

- [ ] **Step 1: Replace fallback expectations with failing strict-localization tests**

Assert that `Barbell_Full_Squat` projects to `杠铃深蹲`, `primary_muscle` becomes `股四头肌`, equipment becomes `杠铃`, and instructions are Chinese. Assert that a compatible exercise missing from the overlay produces blocking `LOCALIZATION_MISSING`, not `ENRICHMENT_ENGLISH_FALLBACK`.

- [ ] **Step 2: Run the focused exercise tests**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/catalog_receiver/test_exercise_projector.py backend/tests/catalog_receiver/test_service.py -q`

Expected: failures show the current English fallback and untranslated taxonomy.

- [ ] **Step 3: Apply record and taxonomy localization in the projector**

For accepted categories, resolve the stable ID before constructing `CanonicalExerciseRecord`. Translate primary and secondary muscles from the taxonomy asset. Preserve upstream values under `provenance.upstream` and expose translated metadata under `provenance.localization`:

```python
provenance={
    "upstream": {
        "name": upstream_name,
        "primary_muscle": primary[0],
        "secondary_muscles": list(secondary),
        "equipment": values.get("equipment"),
        "level": values.get("level"),
        "mechanic": values.get("mechanic"),
        "force": values.get("force"),
        "instructions": values.get("instructions"),
    },
    "localization": {
        "locale": "zh-CN",
        "asset_version": bundle.version,
        "equipment": taxonomy.equipment(values.get("equipment")),
        "level": taxonomy.level(values.get("level")),
        "mechanic": taxonomy.mechanic(values.get("mechanic")),
        "force": taxonomy.force(values.get("force")),
        "instructions": list(entry.instructions_zh_cn),
    },
}
```

- [ ] **Step 4: Author and validate the complete shared taxonomy**

Map every distinct upstream value observed in the 750 accepted records. Allow Latin text only for explicit Mainland abbreviations such as `EZ 杠`, `T 杠`, and `TRX`; do not use a general `[A-Z]+` exception.

- [ ] **Step 5: Run focused projection and service tests**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/catalog_receiver/test_exercise_projector.py backend/tests/catalog_receiver/test_service.py backend/tests/catalog_receiver/test_localization.py -q`

Expected: all tests pass and no fixture record uses English fallback.

- [ ] **Step 6: Commit the strict exercise projection slice**

```powershell
git add backend/catalog_receiver/projectors.py backend/catalog_receiver/validators.py backend/data/catalog/mappings/free-exercise-db.v1.json backend/data/catalog/localizations/exercise-taxonomy.zh-CN.v1.json backend/tests/catalog_receiver
git commit -m "feat: require complete exercise localization"
```

## Task 4: Complete Static Exercise Translation Asset

**Files:**
- Create: `backend/data/catalog/localizations/free-exercise-db.zh-CN.v2.json`
- Modify: `backend/tests/catalog_receiver/test_real_data_acceptance.py`

- [ ] **Step 1: Add failing production coverage tests**

Load the bundled exercise source, localization overlay, and taxonomy. Assert exact source-ID equality, 750 entries, matching instruction-step counts, no unapproved Latin display text, preserved English aliases, no unknown taxonomy values, and no indistinguishable canonical-name collisions.

- [ ] **Step 2: Run the production data test**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/catalog_receiver/test_real_data_acceptance.py -q`

Expected: failure because the complete v2 localization asset does not exist.

- [ ] **Step 3: Translate the 750 stable-ID records in reviewable batches**

Use ten source-ID-sorted batches of at most 75 records. Each batch must emit the exact schema below, with instruction order and count preserved:

```json
{
  "Barbell_Full_Squat": {
    "name_zh_cn": "杠铃深蹲",
    "aliases": ["深蹲", "杠铃全蹲"],
    "instructions_zh_cn": [
      "将杠铃置于上背部并稳定站立。",
      "屈髋屈膝下蹲，保持膝盖与脚尖方向一致。"
    ]
  }
}
```

Treat the executing Agent as an authoring assistant only. After each batch, run the loader against that batch and correct every schema, terminology, collision, and Latin-residual issue before merging. Do not invent exercise IDs, remove upstream steps, or place credentials or generation logs in the repository.

- [ ] **Step 4: Merge batches deterministically and run full data validation**

Sort final JSON entries by source ID and write UTF-8 with `ensure_ascii=False`, two-space indentation, and a terminal newline. Run:

`.venv\Scripts\python.exe -m pytest backend/tests/catalog_receiver/test_localization.py backend/tests/catalog_receiver/test_real_data_acceptance.py -q`

Expected: 750/750 exercise localizations accepted with zero blocking issues.

- [ ] **Step 5: Manually review ambiguity and collision reports**

Review every name collision and every entry containing an allowed abbreviation. Distinguish variants with natural grip, stance, side, angle, equipment, or posture qualifiers. The report must contain zero unresolved items.

- [ ] **Step 6: Commit the reviewed data asset**

```powershell
git add backend/data/catalog/localizations/free-exercise-db.zh-CN.v2.json backend/tests/catalog_receiver/test_real_data_acceptance.py
git commit -m "data: add complete Mainland exercise translations"
```

## Task 5: Deterministic Catalog Build And Receiver CLI

**Files:**
- Modify: `backend/catalog_receiver/service.py`
- Modify: `backend/tools/catalog_receiver.py`
- Modify: `scripts/import_initial_catalogs.py`
- Create: `scripts/build_localized_catalogs.py`
- Create: `backend/tests/catalog_receiver/test_build_localized_catalogs.py`
- Modify: `backend/tests/catalog_receiver/test_cli.py`
- Modify: `backend/tests/catalog_receiver/test_initial_import_script.py`

- [ ] **Step 1: Write failing service, CLI, and atomic-build tests**

Cover repeatable `--localization` and optional `--taxonomy` arguments, missing localization exit code 4, both-source validation before database creation, deterministic output ordering, idempotent repeated builds, and no output replacement on validation failure.

- [ ] **Step 2: Run the command tests**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/catalog_receiver/test_cli.py backend/tests/catalog_receiver/test_initial_import_script.py backend/tests/catalog_receiver/test_build_localized_catalogs.py -q`

Expected: failures because localization arguments and the build script do not exist.

- [ ] **Step 3: Thread localization assets through the receiver service**

Load each asset once per `_run`, pass the immutable bundle to `project_source`, append coverage issues before `build_report`, and block the sink whenever any localization issue has severity `error`. Coverage validation rejects orphan IDs for both catalogs but requires exact source-ID equality only for exercises; an unlisted food falls back to glossary and `tw2sp`.

- [ ] **Step 4: Implement atomic bundled-catalog output**

`scripts/build_localized_catalogs.py` reads the two existing normalized bundled catalogs as its source snapshots. On the first food build, the original Taiwan name comes from the preserved first Chinese source alias; subsequent builds use `provenance.localization.upstream_name`. Exercise input always uses `provenance.upstream_name` and the preserved upstream instruction list. Missing upstream source text is a blocking error.

The script must validate both complete projected catalogs before replacing either normalized file. Write sibling temporary files, flush and `os.fsync`, then use `Path.replace` only after both serializations succeed. On failure, delete only temporary files created by that run and preserve both prior bundled catalogs.

- [ ] **Step 5: Update CLI and initial-import arguments**

Use these explicit arguments:

```powershell
.venv\Scripts\python.exe scripts\import_initial_catalogs.py --foods <tfda.csv> --food-localization backend\data\catalog\localizations\tfda-foods.zh-CN.v1.json --exercises <exercises.json> --exercise-localization backend\data\catalog\localizations\free-exercise-db.zh-CN.v2.json --exercise-taxonomy backend\data\catalog\localizations\exercise-taxonomy.zh-CN.v1.json --database backend\data\fitlife.sqlite3
```

- [ ] **Step 6: Run command tests**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/catalog_receiver/test_cli.py backend/tests/catalog_receiver/test_initial_import_script.py backend/tests/catalog_receiver/test_build_localized_catalogs.py -q`

Expected: all tests pass and repeated builds are byte-identical.

- [ ] **Step 7: Commit the deterministic build slice**

```powershell
git add backend/catalog_receiver/service.py backend/tools/catalog_receiver.py scripts/import_initial_catalogs.py scripts/build_localized_catalogs.py backend/tests/catalog_receiver
git commit -m "feat: build localized catalogs atomically"
```

## Task 6: Regenerate Bundled Catalogs And Verify Persistence

**Files:**
- Modify: `backend/data/catalog/foods.zh-CN.v1.json`
- Modify: `backend/data/catalog/exercises.zh-CN.v1.json`
- Modify: `backend/tests/catalog_receiver/test_real_data_acceptance.py`
- Modify: `backend/tests/infrastructure/test_food_catalog_seed.py`
- Modify: `backend/tests/infrastructure/test_exercise_catalog_seed.py`

- [ ] **Step 1: Add failing seed identity and reimport tests**

Seed the old fixture, save catalog IDs, seed the localized fixture, and assert IDs are unchanged while canonical names, aliases, FTS rows, and provenance update. Create a historical meal/workout snapshot before reimport and assert its stored name remains unchanged afterward.

- [ ] **Step 2: Run persistence tests**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/infrastructure/test_food_catalog_seed.py backend/tests/infrastructure/test_exercise_catalog_seed.py -q`

Expected: new localized reimport assertions fail before regenerated payloads are wired.

- [ ] **Step 3: Build the production normalized catalogs**

Run the deterministic build command against the committed normalized source snapshots and three localization assets:

```powershell
.venv\Scripts\python.exe scripts\build_localized_catalogs.py --foods backend\data\catalog\foods.zh-CN.v1.json --food-localization backend\data\catalog\localizations\tfda-foods.zh-CN.v1.json --exercises backend\data\catalog\exercises.zh-CN.v1.json --exercise-localization backend\data\catalog\localizations\free-exercise-db.zh-CN.v2.json --exercise-taxonomy backend\data\catalog\localizations\exercise-taxonomy.zh-CN.v1.json --food-output backend\data\catalog\foods.zh-CN.v1.json --exercise-output backend\data\catalog\exercises.zh-CN.v1.json
```

Run it twice and require a byte-identical second result. Confirm generated counts remain exactly 2,128 foods and 750 exercises and source-derived IDs are unchanged.

- [ ] **Step 4: Run data and persistence acceptance**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/catalog_receiver/test_real_data_acceptance.py backend/tests/infrastructure/test_food_catalog_seed.py backend/tests/infrastructure/test_exercise_catalog_seed.py -q`

Expected: all tests pass; `米饭`, `杠铃深蹲`, and translated metadata appear in normalized payloads.

- [ ] **Step 5: Inspect generated-data diff**

Confirm numeric nutrients, MET values, source IDs, licenses, attribution, and dataset record counts did not change. Only canonical display text, aliases, localization provenance, translated taxonomy, and instructions may differ.

- [ ] **Step 6: Commit regenerated catalogs**

```powershell
git add backend/data/catalog/foods.zh-CN.v1.json backend/data/catalog/exercises.zh-CN.v1.json backend/tests/catalog_receiver/test_real_data_acceptance.py backend/tests/infrastructure/test_food_catalog_seed.py backend/tests/infrastructure/test_exercise_catalog_seed.py
git commit -m "data: publish Mainland localized catalogs"
```

## Task 7: API, Frontend, Documentation, And Final Acceptance

**Files:**
- Modify: `backend/tests/test_food_catalog_api.py`
- Modify: `backend/tests/test_workout_drafts_api.py`
- Modify: `frontend/src/components/meals/FoodCatalogPane.test.tsx`
- Modify: `frontend/src/components/workouts/ExerciseCatalogPane.test.tsx`
- Modify: `README.md`

- [ ] **Step 1: Write failing API compatibility tests**

For food, search `米饭`, `白饭`, `米飯`, and `Cooked rice`; assert the selected public record always displays `米饭`. For exercise, search `杠铃深蹲` and `Barbell Full Squat`; assert the same stable record displays `杠铃深蹲` and `primary_muscle == "股四头肌"`.

- [ ] **Step 2: Write frontend rendering tests**

Mock the existing service responses and assert catalog result cards render `米饭`, `杠铃深蹲`, and `股四头肌` without changing the API type contract or adding client-side translation logic.

- [ ] **Step 3: Run focused API and frontend tests**

Run backend:

`.venv\Scripts\python.exe -m pytest backend/tests/test_food_catalog_api.py backend/tests/test_workout_drafts_api.py -q`

Run frontend:

```powershell
Set-Location -LiteralPath 'frontend'
npm test -- src/components/meals/FoodCatalogPane.test.tsx src/components/workouts/ExerciseCatalogPane.test.tsx
Set-Location -LiteralPath '..'
```

Expected: all focused tests pass.

- [ ] **Step 4: Document operational boundaries**

Document the three committed localization assets, deterministic build command, validation report, stable-ID behavior, alias compatibility, OpenCC Apache-2.0 attribution, and the rule that startup/runtime never calls an Agent or translation service.

- [ ] **Step 5: Run the backend catalog and API regression suite**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/catalog_receiver backend/tests/infrastructure/test_food_catalog_seed.py backend/tests/infrastructure/test_exercise_catalog_seed.py backend/tests/infrastructure/test_sqlite_food_catalog_repository.py backend/tests/infrastructure/test_sqlite_exercise_catalog_repository.py backend/tests/test_food_catalog_api.py backend/tests/test_workout_drafts_api.py backend/tests/test_startup_readiness.py -q`

Expected: all tests pass.

- [ ] **Step 6: Run frontend tests and production build**

```powershell
Set-Location -LiteralPath 'frontend'
npm test
npm run build
Set-Location -LiteralPath '..'
```

Expected: Vitest passes and Vite completes a production build.

- [ ] **Step 7: Rebuild Docker and verify readiness**

```powershell
docker compose down
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://127.0.0.1:19000/health/ready
```

Expected: backend and frontend are healthy; readiness reports `ready` with zero catalog failures.

- [ ] **Step 8: Browser acceptance**

At desktop `1280x720` and mobile `390x844`, sign in and verify:

- meal search by `米饭`, `白饭`, and `Cooked rice` shows `米饭`;
- workout search by `杠铃深蹲` and `Barbell Full Squat` shows `杠铃深蹲` and Chinese muscle text;
- adding and confirming both records succeeds;
- a restart preserves confirmed snapshots;
- no console errors or horizontal overflow occur.

- [ ] **Step 9: Commit final tests and documentation**

```powershell
git add backend/tests/test_food_catalog_api.py backend/tests/test_workout_drafts_api.py frontend/src/components/meals/FoodCatalogPane.test.tsx frontend/src/components/workouts/ExerciseCatalogPane.test.tsx README.md
git commit -m "test: verify Mainland catalog experience"
```

## Final Review Gate

- [ ] Confirm `git diff --check` passes.
- [ ] Confirm `git status --short` contains only intentionally retained pre-existing changes.
- [ ] Confirm production data counts remain 2,128 foods and 750 exercises.
- [ ] Confirm no approved catalog display name uses Taiwan-only wording or unapproved English text.
- [ ] Confirm old Taiwan and English aliases still search the same stable records.
- [ ] Confirm no model key, `.env`, SQLite file, translation prompt log, or temporary batch file is staged.
- [ ] Run `git log --oneline -8` and verify each implementation slice is independently understandable.
