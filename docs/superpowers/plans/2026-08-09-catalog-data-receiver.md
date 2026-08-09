# Catalog Data Receiver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic local CSV/JSON receiver that inspects, maps, validates, reports, and atomically imports Taiwan FDA food data and free-exercise-db data through the existing SQLite catalog infrastructure.

**Architecture:** A physical reader produces bounded source documents, an inspector describes them, a validated mapping profile drives safe projectors, catalog validators produce canonical records and coded issues, and a sink delegates persistence to the existing seed/import-ledger code. CLI and initial-import scripts are thin adapters around one service; no Agent, network input, HTTP upload, or profile-executed code is allowed.

**Tech Stack:** Python 3.12, Pydantic v2, stdlib csv/json/hashlib/argparse, JMESPath, OpenCC, SQLite, pytest.

---

## File Structure

- `backend/catalog_receiver/models.py`: Pydantic contracts for profiles, source descriptions, canonical records, issues, reports, and service results.
- `backend/catalog_receiver/readers.py`: local path checks, bounded CSV/JSON parsing, hashes, encodings, and physical errors.
- `backend/catalog_receiver/inspector.py`: CSV/JSON structure discovery, samples, mapping candidates, and draft profiles.
- `backend/catalog_receiver/mapping.py`: mapping-profile loading and allow-listed transform execution.
- `backend/catalog_receiver/projectors.py`: row projection, Taiwan grouped nutrient pivot, free-exercise projection, and enrichment merge.
- `backend/catalog_receiver/validators.py`: canonical food/exercise validation and stable issue generation.
- `backend/catalog_receiver/reporting.py`: JSON/text reports and normalized audit snapshots.
- `backend/catalog_receiver/sinks.py`: normalized payload adapters, existing seed-loader calls, and public-source retirement.
- `backend/catalog_receiver/service.py`: inspect/validate/import orchestration with no CLI concerns.
- `backend/tools/catalog_receiver.py`: argparse CLI and exit-code translation.
- `backend/data/catalog/mappings/*.json`: versioned built-in profiles.
- `backend/data/catalog/enrichments/free-exercise-db.zh-CN.v1.json`: reviewed optional ID-keyed Chinese enrichment.
- `scripts/import_initial_catalogs.py`: validate-both-before-write two-source command.
- `backend/tests/catalog_receiver/`: unit and integration coverage for every receiver stage.

### Task 1: Contracts, dependencies, and physical readers

**Files:**
- Create: `backend/catalog_receiver/__init__.py`
- Create: `backend/catalog_receiver/models.py`
- Create: `backend/catalog_receiver/readers.py`
- Create: `backend/tests/catalog_receiver/test_readers.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Write failing reader tests**

Cover UTF-8/BOM CSV, embedded newlines, duplicate headers, missing file, URL/directory/extension rejection, invalid encoding, JSON root data, malformed JSON, and a configurable JSON byte limit. Assert `ReceiverError.code` is one of `SOURCE_NOT_FOUND`, `SOURCE_URL_UNSUPPORTED`, `SOURCE_EXTENSION_UNSUPPORTED`, `CSV_HEADERS_DUPLICATE`, `SOURCE_ENCODING_INVALID`, `JSON_INVALID`, and `JSON_SIZE_LIMIT_EXCEEDED`.

- [ ] **Step 2: Verify the tests fail**

Run: `python -m pytest backend/tests/catalog_receiver/test_readers.py -q`

Expected: collection fails because `backend.catalog_receiver` does not exist.

- [ ] **Step 3: Implement contracts and readers**

Define `ReceiverIssue`, `ReceiverError`, `SourceMetadata`, `CsvSource`, `JsonSource`, `MappingProfile`, canonical record models, `ReceiverReport`, and `ReceiverResult`. Implement `read_source(path, json_size_limit=100_000_000)` with resolved local paths, SHA-256, basename-only persisted metadata, `utf-8-sig` first, CSV `Sniffer`, duplicate-header checks, streamed row mappings, and bounded JSON loading. Add pinned lower bounds `jmespath>=1.1.0` and `opencc-python-reimplemented>=0.1.7`.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest backend/tests/catalog_receiver/test_readers.py -q`

Expected: all reader tests pass.

- [ ] **Step 5: Commit**

Run: `git add requirements.txt backend/catalog_receiver backend/tests/catalog_receiver/test_readers.py && git commit -m "feat: add catalog source readers"`

### Task 2: Structure inspection and mapping profiles

**Files:**
- Create: `backend/catalog_receiver/inspector.py`
- Create: `backend/catalog_receiver/mapping.py`
- Create: `backend/tests/catalog_receiver/test_inspector.py`
- Create: `backend/tests/catalog_receiver/test_mapping.py`

- [ ] **Step 1: Write failing inspection and mapping tests**

Assert CSV reports headers/row count/samples; JSON reports object/array paths and candidate record arrays; only unique aliases yield automatic canonical candidates; ambiguity is reported instead of guessed. Assert unknown transforms, arbitrary expression keys, invalid selectors, missing metadata, and incompatible source/profile formats raise `MAPPING_PROFILE_INVALID`; verify `strip`, `number`, `first`, `list`, `constant`, `enum_map`, `opencc_t2s`, and `lower` behavior.

- [ ] **Step 2: Verify red state**

Run: `python -m pytest backend/tests/catalog_receiver/test_inspector.py backend/tests/catalog_receiver/test_mapping.py -q`

Expected: imports fail for missing inspector and mapping modules.

- [ ] **Step 3: Implement inspection and safe mapping**

Walk bounded JSON recursively, record paths/types/examples, use JMESPath only for selectors, and build a draft profile with explicit unresolved fields. Validate profile schema with Pydantic `extra="forbid"`; represent each transform as a discriminated object and execute only the eight approved operations. Reject all callable/module/expression concepts.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest backend/tests/catalog_receiver/test_inspector.py backend/tests/catalog_receiver/test_mapping.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run: `git add backend/catalog_receiver backend/tests/catalog_receiver && git commit -m "feat: inspect catalog layouts and validate mappings"`

### Task 3: Taiwan grouped-pivot projection

**Files:**
- Create: `backend/catalog_receiver/projectors.py`
- Create: `backend/data/catalog/mappings/tfda-foods.v1.json`
- Create: `backend/tests/catalog_receiver/fixtures/tfda-foods.csv`
- Create: `backend/tests/catalog_receiver/test_tfda_projector.py`

- [ ] **Step 1: Write failing Taiwan projection tests**

Use Traditional Chinese fixture headers matching the audited upstream CSV. Assert grouping by `整合編號`, four nutrient pivots, `per_100g`/100/`g`, Simplified display name, preserved Traditional alias, deterministic source identity, provenance, inconsistent descriptor detection, duplicate nutrient handling, unsupported units, missing nutrient issues, and invalid numeric issues.

- [ ] **Step 2: Verify red state**

Run: `python -m pytest backend/tests/catalog_receiver/test_tfda_projector.py -q`

Expected: projector/profile is missing.

- [ ] **Step 3: Implement grouped projection and profile**

Group rows without loading a second copy, select stable descriptive fields, pivot `修正熱量`, `總碳水化合物`, `粗蛋白`, and `粗脂肪`, normalize number strings, create OpenCC Simplified names while retaining Traditional/common/English aliases, and attach source nutrient labels plus transformations to provenance.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest backend/tests/catalog_receiver/test_tfda_projector.py -q`

Expected: all Taiwan tests pass.

- [ ] **Step 5: Commit**

Run: `git add backend/catalog_receiver backend/data/catalog/mappings backend/tests/catalog_receiver && git commit -m "feat: project Taiwan food catalog data"`

### Task 4: Exercise projection and Chinese enrichment

**Files:**
- Create: `backend/data/catalog/mappings/free-exercise-db.v1.json`
- Create: `backend/data/catalog/enrichments/free-exercise-db.zh-CN.v1.json`
- Create: `backend/tests/catalog_receiver/fixtures/free-exercises.json`
- Create: `backend/tests/catalog_receiver/fixtures/free-exercises.zh-CN.json`
- Create: `backend/tests/catalog_receiver/test_exercise_projector.py`
- Modify: `backend/catalog_receiver/projectors.py`

- [ ] **Step 1: Write failing exercise tests**

Assert category counts and mapping, explicit `stretching` exclusion, primary/secondary muscles, null MET, full upstream metadata in provenance, English fallback, Chinese name/alias/pinyin merge, coverage count/percentage, duplicate enrichment key/value rejection, invalid pinyin rejection, unknown ID/orphan reporting, and no invention of Chinese names.

- [ ] **Step 2: Verify red state**

Run: `python -m pytest backend/tests/catalog_receiver/test_exercise_projector.py -q`

Expected: exercise profile and enrichment support are missing.

- [ ] **Step 3: Implement exercise projection**

Map `strength`, `plyometrics`, `powerlifting`, `olympic weightlifting`, and `strongman` to `strength`; map only `cardio` to `cardio`; exclude `stretching` with `EXERCISE_CATEGORY_EXCLUDED`. Preserve equipment, level, mechanic, force, instructions, images, and original category in provenance while omitting image ingestion. Validate enrichment as an ID-keyed object and report fallback coverage.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest backend/tests/catalog_receiver/test_exercise_projector.py -q`

Expected: all exercise tests pass.

- [ ] **Step 5: Commit**

Run: `git add backend/catalog_receiver backend/data/catalog backend/tests/catalog_receiver && git commit -m "feat: project and enrich exercise catalog data"`

### Task 5: Validation, reports, and receiver service

**Files:**
- Create: `backend/catalog_receiver/validators.py`
- Create: `backend/catalog_receiver/reporting.py`
- Create: `backend/catalog_receiver/service.py`
- Create: `backend/tests/catalog_receiver/test_validation_reporting.py`
- Create: `backend/tests/catalog_receiver/test_service.py`

- [ ] **Step 1: Write failing validation/service tests**

Assert required food nutrients and basis, supported exercise type/nonempty muscle, finite nonnegative numbers, source metadata, duplicate identity, owner boundary, complete row scanning, 1,000-detail cap, canonical schema/example on mapping/type failures, basename-only source metadata, JSON/text reports, normalized snapshots only after successful normalization, dry-run no writes, and any blocking issue preventing sink invocation.

- [ ] **Step 2: Verify red state**

Run: `python -m pytest backend/tests/catalog_receiver/test_validation_reporting.py backend/tests/catalog_receiver/test_service.py -q`

Expected: modules are missing.

- [ ] **Step 3: Implement validators, reporting, and orchestration**

Implement stable code-to-message/suggestion rendering and aggregate counts. `CatalogReceiver.inspect`, `.validate`, and `.import_catalog` must share one read/map/project/validate path; import calls a sink only after zero errors. Reports contain source fingerprint, mapping/source metadata, scanned/accepted/excluded/rejected/coverage/issue counts, transaction result and duration; output uses atomic file replacement.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest backend/tests/catalog_receiver/test_validation_reporting.py backend/tests/catalog_receiver/test_service.py -q`

Expected: all service tests pass.

- [ ] **Step 5: Commit**

Run: `git add backend/catalog_receiver backend/tests/catalog_receiver && git commit -m "feat: validate and report catalog imports"`

### Task 6: SQLite sink and retirement boundaries

**Files:**
- Create: `backend/catalog_receiver/sinks.py`
- Create: `backend/tests/catalog_receiver/test_sqlite_sink.py`
- Modify: `backend/infrastructure/catalog/seed_foods.py`
- Modify: `backend/infrastructure/catalog/seed_exercises.py`

- [ ] **Step 1: Write failing sink integration tests**

Assert normalized payloads use current seed loaders; same version/checksum skips; completed version/checksum drift rejects; a bad record rolls back; missing managed records deactivate; explicit retired sources deactivate only public rows and search entries; private rows and historical meal/workout snapshots remain unchanged; Chinese/Traditional/English/alias/pinyin searches work.

- [ ] **Step 2: Verify red state**

Run: `python -m pytest backend/tests/catalog_receiver/test_sqlite_sink.py -q`

Expected: sink is missing.

- [ ] **Step 3: Implement sink adapters**

Expose payload-based entry points in the seed modules while preserving path-based startup APIs. Build schema-version-1 normalized payloads in memory, call existing `CatalogImportLedger` transaction paths, and implement explicit retirement inside a ledger-protected transaction constrained by `owner_user_id IS NULL`; delete only matching public search rows.

- [ ] **Step 4: Run focused and regression tests**

Run: `python -m pytest backend/tests/catalog_receiver/test_sqlite_sink.py backend/tests/infrastructure/test_food_catalog_seed.py backend/tests/infrastructure/test_exercise_catalog_seed.py -q`

Expected: all sink and existing seed tests pass.

- [ ] **Step 5: Commit**

Run: `git add backend/catalog_receiver backend/infrastructure/catalog backend/tests/catalog_receiver && git commit -m "feat: import normalized catalogs atomically"`

### Task 7: CLI and two-source initial import

**Files:**
- Create: `backend/tools/catalog_receiver.py`
- Create: `backend/tests/catalog_receiver/test_cli.py`
- Create: `scripts/import_initial_catalogs.py`
- Create: `backend/tests/catalog_receiver/test_initial_import_script.py`

- [ ] **Step 1: Write failing command tests**

Test `inspect`, `validate`, and `import`; `--mapping`, `--database`, `--output-dir`, and JSON-size options; unsupported inputs; machine/human reports; and exact exits 0/2/3/4/5. For the initial script assert both files validate before the first sink call, each source write is independently atomic/retryable, and a second run skips.

- [ ] **Step 2: Verify red state**

Run: `python -m pytest backend/tests/catalog_receiver/test_cli.py backend/tests/catalog_receiver/test_initial_import_script.py -q`

Expected: command modules are missing.

- [ ] **Step 3: Implement thin commands**

Use `argparse`; never download or accept URL input. Translate only typed receiver failures to documented exits. The initial script loads the two built-in profiles, optional enrichment, and one configured `SQLiteDatabase`; it validates both inputs first, then imports each validated result independently.

- [ ] **Step 4: Run command tests and help smoke tests**

Run: `python -m pytest backend/tests/catalog_receiver/test_cli.py backend/tests/catalog_receiver/test_initial_import_script.py -q`

Run: `python -m backend.tools.catalog_receiver --help`

Run: `python scripts/import_initial_catalogs.py --help`

Expected: tests pass and both help commands exit 0.

- [ ] **Step 5: Commit**

Run: `git add backend/tools backend/catalog_receiver scripts/import_initial_catalogs.py backend/tests/catalog_receiver && git commit -m "feat: add catalog receiver commands"`

### Task 8: Production snapshots and startup cutover

**Files:**
- Modify: `backend/data/catalog/foods.zh-CN.v1.json`
- Modify: `backend/data/catalog/exercises.zh-CN.v1.json`
- Modify: `backend/infrastructure/startup.py`
- Modify: `backend/tests/test_startup_readiness.py`
- Create: `backend/tests/catalog_receiver/test_real_data_acceptance.py`
- Modify: `README.md`

- [ ] **Step 1: Acquire upstream files manually for development validation**

Download only to an ignored temporary directory using the two approved public URLs. Record SHA-256 and upstream date in reports; do not add raw files or downloader code to the product.

- [ ] **Step 2: Run real-data validation before modifying bundled snapshots**

Run the receiver `validate` command against both files and assert Taiwan accepts 2,181 foods; exercise input reports 873 total, 123 stretching exclusions, and 750 accepted compatible records unless the report clearly identifies upstream drift.

- [ ] **Step 3: Materialize reviewed normalized snapshots**

Use the initial script output to replace demonstration-sized normalized JSON files. Keep license, attribution, provenance, aliases, source IDs, and mapping/profile version. Retire prior demo public sources in the profiles while preserving private and historical records.

- [ ] **Step 4: Test startup and search acceptance**

Run: `python -m pytest backend/tests/catalog_receiver/test_real_data_acceptance.py backend/tests/test_startup_readiness.py backend/tests/test_food_catalog_api.py backend/tests/test_workout_drafts_api.py -q`

Expected: startup is idempotent, readiness remains healthy, counts match reports, and representative multilingual searches pass.

- [ ] **Step 5: Document operator workflow and commit**

Document direct public download links, local-file-only scope, inspect/validate/import commands, expected formats, exit codes, report artifacts, and the initial script. Then run: `git add backend/data/catalog backend/infrastructure/startup.py backend/tests README.md && git commit -m "data: bundle public food and exercise catalogs"`

### Task 9: Full verification and branch completion

**Files:**
- Modify only files required by failures discovered below.

- [ ] **Step 1: Run catalog receiver suite**

Run: `python -m pytest backend/tests/catalog_receiver -q`

Expected: all pass.

- [ ] **Step 2: Run complete backend suite**

Run: `python -m pytest backend/tests -q`

Expected: at least the 772 baseline tests plus new tests pass.

- [ ] **Step 3: Exercise CLI failure and idempotency paths**

Run inspect on an unsupported file and verify exit 2; run validate on a malformed fixture and verify exit 4 plus schema/example; import into a temporary SQLite database twice and verify the second run reports skipped with stable row counts.

- [ ] **Step 4: Verify Docker readiness**

Run: `docker compose up --build -d`

Run: `Invoke-RestMethod http://127.0.0.1:19000/health/ready`

Expected: readiness reports success. If configured host ports differ, use the values in `docker compose ps`.

- [ ] **Step 5: Review and finish branch**

Run: `git diff main...HEAD --check`

Run: `git status --short --branch`

Use the finishing-development-branch workflow; merge only after tests and review pass, and push only with user authorization.

## Self-Review

- Spec coverage: all included boundaries, both projection strategies, enrichment fallback, retirement, report artifacts, exit codes, real-data counts, atomicity, idempotency, and startup cutover map to Tasks 1-9.
- Exclusion coverage: reader/CLI tests reject URLs and unsupported formats; no Agent, HTTP route, downloader, arbitrary transform execution, exercise images, stretching coercion, or first-class provenance metadata fields are introduced.
- Placeholder scan: no TBD/TODO/follow-up implementation placeholders remain.
- Type consistency: `MappingProfile`, canonical records, `ReceiverIssue`, `ReceiverReport`, `ReceiverResult`, and `CatalogReceiver` are introduced once and reused by service, sink, CLI, and scripts.
