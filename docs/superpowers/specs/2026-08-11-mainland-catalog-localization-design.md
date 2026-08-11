# Mainland Catalog Localization Design

**Status:** Approved for implementation

**Date:** 2026-08-11
**Scope:** Mainland Chinese display names and user-visible metadata for the bundled Taiwan FDA food catalog and `free-exercise-db` exercise catalog.

## Goal

Make every bundled public catalog record read naturally to a Mainland Chinese user without losing source identity, provenance, or search compatibility.

The delivered catalogs contain:

- 2,128 active Taiwan FDA food records;
- 750 active `free-exercise-db` exercise records.

Food and exercise pages display Mainland Chinese names. English names, Taiwan names, and upstream names remain searchable aliases and provenance, but are not the primary display names.

## Current Problem

The food receiver currently applies OpenCC `t2s`. This converts characters but does not reliably normalize regional food terms. Names such as `白饭` remain unfamiliar as primary Mainland search terms even though users expect `米饭`.

The exercise enrichment contains only 6 records. The remaining 744 exercise names fall back to English. Primary and secondary muscles, equipment, level, mechanics, force, and exercise instructions also remain in English.

Blind in-place replacement is not acceptable because it would:

- discard licensed upstream names and attribution context;
- break searches using old names;
- make future source refreshes difficult to reconcile;
- create ambiguous duplicate translations;
- make translation quality impossible to audit independently from source data.

## Decisions

### 1. Versioned Localization Overlays

Localization is a separate, versioned data layer keyed by stable `source_record_id`.

The source catalogs remain authoritative for nutrition, exercise structure, source identity, license, attribution, and upstream text. Localization overlays are authoritative only for Mainland Chinese display text.

Planned assets:

- `backend/data/catalog/localizations/tfda-foods.zh-CN.v1.json` for record-specific food display names and reviewed aliases;
- `backend/data/catalog/localizations/free-exercise-db.zh-CN.v2.json` for exercise display names and translated instructions;
- `backend/data/catalog/localizations/exercise-taxonomy.zh-CN.v1.json` for shared muscle, equipment, level, mechanic, force, and category terminology.

The existing normalized seed files remain the runtime input. They are regenerated from source plus localization overlays and keep their current stable source IDs.

### 2. Deterministic Runtime Boundary

Catalog inspection, validation, projection, seeding, and startup import remain deterministic. They do not call an Agent, translation API, or network service.

An Agent may assist authors in producing the initial static translation assets during development. Generated text is not trusted directly: it must pass schema, glossary, coverage, collision, residual-English, and source-identity checks before it can be committed. No model credential or generated request log is stored in the repository.

### 3. Source Preservation

For every record:

- the Mainland Chinese name becomes the canonical display name;
- the upstream name, Taiwan name, English name, and useful common names remain aliases;
- upstream instructions remain in provenance alongside the translated instructions;
- source name, source record ID, dataset version, license, and attribution remain unchanged;
- historical meal and workout snapshots are not rewritten.

## Food Localization

Food localization uses three ordered stages:

1. Read the original Taiwan name retained by the receiver rather than repeatedly converting an already simplified value.
2. Apply OpenCC `tw2sp`, which covers Traditional Chinese characters and Mainland regional phrases.
3. Apply the versioned project food glossary and any record-specific override required for an unambiguous Mainland name.

Examples include:

| Source or Taiwan term | Mainland display term |
|---|---|
| 白饭 | 米饭 |
| 鲔鱼 | 金枪鱼 |
| 马铃薯 | 土豆 |
| 青花菜 | 西兰花 |
| 奇异果 | 猕猴桃 |
| 凤梨 | 菠萝 |

The glossary is not a global string-replacement table. Rules operate on parsed names and can be overridden by `source_record_id` where context changes meaning. Taiwan-specific foods or regional species without a colloquial Mainland equivalent remain present under an accepted Mainland standard Chinese name.

Preparation method, cut, state, and other distinguishing qualifiers are preserved. If normalization causes a collision, records receive a natural qualifier rather than an internal ID.

## Exercise Localization

All 750 accepted exercise IDs require a localization entry. English fallback is removed from production catalog generation.

Each exercise localization contains:

- `name_zh_cn`;
- searchable aliases, including the upstream English name;
- `instructions_zh_cn`, aligned in order with upstream instruction steps;
- an optional review note for terminology that needs an explicit rationale.

Shared taxonomy is translated once through an allow-listed dictionary:

- primary and secondary muscles;
- equipment;
- difficulty level;
- mechanic;
- force;
- source category.

Exercise names follow common Mainland fitness wording: equipment or posture first, followed by the movement, with side, grip, angle, and stance qualifiers retained. For example, `Barbell Full Squat` displays as `杠铃深蹲` while both terms resolve to the same record.

Common Mainland abbreviations such as `EZ 杠`, `T 杠`, and `TRX` are allowed only through an explicit allow-list. Other Latin text in a display field is a blocking validation error.

## Data Flow

1. A local source file is inspected and projected through the existing catalog receiver.
2. The projector resolves the matching localization by catalog kind and stable source ID.
3. Food conversion and overrides produce the Mainland canonical name.
4. Exercise record localization and shared taxonomy produce all user-visible Chinese fields.
5. Original names and text are merged into aliases and provenance.
6. Validation runs over the complete projected catalog before any write.
7. The normalized bundled catalog is written atomically.
8. A checksum change causes the existing import ledger to replace the active source partition in one transaction.
9. FTS rows include canonical names and preserved aliases, so old and new search terms remain valid.

The API and frontend continue to consume the existing catalog contracts. No translation logic is added to React components or request handlers.

## Validation And Failure Handling

The build or import fails without changing the active database catalog when any of these conditions occurs:

- a known source ID has no localization;
- a localization refers to an unknown or duplicate source ID;
- a required display name or translated instruction is blank;
- translated exercise instruction count differs from the upstream step count;
- a taxonomy value has no approved translation;
- a display field contains Latin text outside the explicit abbreviation allow-list;
- two records collapse to an indistinguishable display name;
- a source ID, license, attribution, or upstream name is lost;
- an alias duplicates the canonical name after normalization.

Validation produces a machine-readable report grouped by issue code and source ID. Low-confidence authoring output never enters the runtime catalog merely because it is syntactically valid.

Import remains transaction-scoped. A failed localized catalog leaves the prior active partition and FTS rows intact.

## Search And Compatibility

Search is backward compatible:

- `米饭`, `白饭`, `米飯`, and `rice` can resolve the same food record when present in its source aliases;
- `深蹲` and `Barbell Full Squat` resolve the same exercise record;
- only the Mainland canonical name is returned as the primary display name.

Stable source-derived catalog IDs remain unchanged, so saved drafts, usage counters, private catalogs, and historical snapshots keep their current ownership and identity behavior.

## Open-Source Practice

- OpenCC explicitly separates character conversion from regional phrase conversion and provides `tw2sp` for Taiwan Traditional Chinese to Simplified Chinese with Mainland phrases. OpenCC is Apache-2.0 licensed.
- `free-exercise-db` is Unlicense and preserves stable source identities, but no reliable open-source Simplified Chinese overlay covering this repository's full accepted set was found. The project therefore owns and reviews its versioned localization overlay.
- The existing import-ledger and source-partition design remains the atomic deployment mechanism; localization does not introduce an alternate write path.

References:

- <https://github.com/BYVoid/OpenCC>
- <https://github.com/yuhonas/free-exercise-db>

## Verification

### Unit Tests

- OpenCC `tw2sp` transform and food glossary precedence;
- record-specific override behavior;
- exercise taxonomy mapping;
- localization schema and duplicate-ID rejection;
- Latin allow-list and collision detection;
- original-name alias preservation.

### Data Acceptance Tests

- exactly 2,128 food IDs and 750 exercise IDs are represented;
- 100% of active records have a non-empty Mainland display name;
- 100% of exercise instruction steps are localized;
- no unapproved English fallback or untranslated taxonomy remains;
- every source ID, license, attribution, and upstream name survives regeneration;
- generated names are distinguishable.

### Integration Tests

- checksum-triggered reimport updates catalog display data;
- a failed import preserves the previous source partition and FTS index;
- English and Taiwan aliases still find the Mainland canonical record;
- private catalog ownership and historical record snapshots are unchanged.

### Browser Acceptance

- food search and meal entry display Mainland names;
- exercise search and workout entry display Mainland names and Chinese metadata;
- searches by old Taiwan terms and English upstream names still resolve;
- confirmed meal and workout records retain the selected localized snapshot after restart.

## Excluded Scope

- replacing the two upstream datasets;
- deleting Taiwan-specific or uncommon foods;
- runtime Agent translation;
- runtime external catalog or translation APIs;
- rewriting historical meal or workout snapshots;
- account data export;
- exercise images;
- multilingual catalog display beyond the approved Mainland Chinese canonical names and preserved search aliases.
