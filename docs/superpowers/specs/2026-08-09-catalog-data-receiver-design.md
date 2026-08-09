# Catalog Data Receiver Design

**Status:** Approved
**Date:** 2026-08-09
**Scope:** Local CSV/JSON inspection, mapping, validation, normalization, reporting, and controlled import for public food and exercise catalogs.

## Goal

Build one deterministic data receiver that can inspect unfamiliar local CSV and JSON layouts, propose safe field mappings, validate records, explain every blocking issue, and import complete public catalog records through the existing SQLite catalog infrastructure.

The first production profiles cover:

- Taiwan FDA Food Nutrient Database CSV;
- `free-exercise-db` combined JSON;
- a separately reviewed Simplified Chinese exercise-name and alias enrichment file.

The receiver must remain reusable for later catalog sources without copying parsing, validation, reporting, or database-write logic.

## Current System

The product already has the required persistent catalog foundation:

- `food_catalog` and `exercise_catalog` public/private ownership boundaries;
- stable source IDs and source-scoped uniqueness;
- aliases and FTS5 search;
- license, attribution, provenance, version, checksum, and active-state fields;
- transaction-scoped catalog imports and an import ledger;
- idempotent startup seeding and source-record deactivation;
- authenticated food and exercise search APIs.

The current bundled data is demonstration-sized: eight foods, six strength exercises, and four cardio activities. The existing seed loaders accept project-specific normalized JSON, not the upstream Taiwan FDA long-form CSV or the upstream `free-exercise-db` JSON schema.

## Public Data Sources

### Taiwan FDA Food Nutrient Database

- Dataset page: <https://data.gov.tw/dataset/8543>
- CSV download: <https://data.fda.gov.tw/opendata/exportDataList.do?method=ExportData&InfoId=20&logType=2>
- JSON download: <https://data.fda.gov.tw/opendata/exportDataList.do?method=ExportData&InfoId=20&logType=5>
- License: Taiwan Government Open Data License, version 1.0.

The audited CSV contained 226,824 long-form nutrient rows for 2,181 unique foods. Every food had energy, total carbohydrate, crude protein, and crude fat values. Names are Traditional Chinese and may include common and English names.

### free-exercise-db

- Repository: <https://github.com/yuhonas/free-exercise-db>
- Combined JSON: <https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json>
- License: Unlicense.

The audited upstream tree contained 873 exercise JSON records. The combined JSON was approximately 1 MB. Images are excluded from this program.

The audited category distribution was:

| Category | Records | First-version handling |
|---|---:|---|
| strength | 581 | Map to `strength` |
| stretching | 123 | Exclude with an explicit reason |
| plyometrics | 61 | Map to `strength` |
| powerlifting | 38 | Map to `strength` |
| olympic weightlifting | 35 | Map to `strength` |
| strongman | 21 | Map to `strength` |
| cardio | 14 | Map to `cardio` |

Upstream names are primarily English. Chinese names and aliases are a separate enrichment source and never overwrite upstream identity or provenance.

## Boundaries

### Included

- local `.csv` and `.json` files;
- CSV dialect, encoding, header, and row inspection;
- JSON root and nested-array discovery;
- automatic candidate mapping for unambiguous fields;
- explicit, versioned mapping profiles;
- ordinary row projection and grouped/pivoted projection;
- deterministic, allow-listed field transformations;
- complete dry-run validation before writes;
- text and machine-readable reports;
- normalized audit snapshots;
- controlled SQLite imports through existing catalog infrastructure;
- public-source retirement without changing private catalog data or historical snapshots;
- optional Chinese exercise enrichment with English fallback and coverage reporting.

### Excluded

- URL or network input;
- automatic downloads;
- ZIP, XML, Excel, NDJSON, API, or object-storage input;
- an HTTP upload or administrator import endpoint;
- Agent-based mapping, translation, validation, or database writes;
- arbitrary Python expressions or plugins in mapping files;
- exercise images;
- importing stretching as strength or cardio;
- equipment, difficulty, mechanics, or instructions as first-class searchable database fields;
- partial writes when blocking validation errors exist.

Unsupported input returns a coded error and the accepted file extensions. Taiwan FDA ZIP files must be extracted by the operator before use.

## Open-Source Practice

The design adopts the inspect-describe-validate-report flow used by the MIT-licensed Frictionless Framework without adding its broader format and platform dependency surface. Nested JSON selection uses the MIT-licensed JMESPath implementation. Existing Pydantic v2 models define mapping profiles, canonical records, reports, and generated examples.

Python's standard CSV and JSON readers remain the physical parsers. CSV is streamed. JSON has a default 100 MB limit because arbitrary nested selection requires a bounded in-memory document in the first version.

## Architecture

```text
Local file
  -> SourceReader
  -> StructureInspector
  -> MappingEngine
  -> RecordProjector
  -> CatalogValidator
  -> dry-run report
  -> CatalogSink
  -> existing import ledger and SQLite transaction
```

### SourceReader

`SourceReader` accepts one resolved local file path. It rejects directories, missing files, URLs, unsupported extensions, oversized JSON documents, invalid encodings, malformed JSON, ambiguous CSV dialects, and duplicate CSV headers.

CSV rows are exposed as mappings. JSON is loaded as a bounded document and queried through JMESPath.

### StructureInspector

`StructureInspector` reports:

- file kind, size, encoding, and SHA-256;
- CSV headers, inferred dialect, row count, and sample values;
- JSON object/array paths, candidate record arrays, field paths, types, and sample values;
- unambiguous field mapping candidates;
- ambiguous or missing required canonical fields;
- a draft mapping profile.

Inspection never writes normalized files or touches SQLite.

### MappingEngine

`MappingEngine` applies an explicit Pydantic-validated mapping profile. A profile declares:

- profile name and version;
- source kind, source name, dataset version, license, and attribution;
- input format and physical options;
- JSON record selector or CSV grouping key;
- canonical field selectors;
- constants, category maps, filters, and pivot rules;
- allow-listed transformations;
- optional enrichment identity and coverage policy;
- explicitly retired public sources.

The allow-listed transformations are:

- `strip`;
- `number`;
- `first`;
- `list`;
- `constant`;
- `enum_map`;
- `opencc_t2s`;
- `lower`.

Mapping files cannot import modules, call functions, evaluate expressions, or execute code.

### RecordProjector

Two projection strategies are supported:

1. `row`: one source object or CSV row becomes one canonical candidate;
2. `grouped_pivot`: rows sharing a configured identity are grouped and selected values are pivoted by a configured key.

The Taiwan FDA profile groups by `整合編號`, takes stable descriptive fields from the group, and pivots `分析項`/`每100克含量` into:

- `修正熱量` -> `calories`;
- `總碳水化合物` -> `carbs`;
- `粗蛋白` -> `protein`;
- `粗脂肪` -> `fat`.

The canonical basis is `per_100g`, amount `100`, unit `g`. Traditional names remain aliases. A deterministic OpenCC conversion creates the Simplified Chinese display candidate while preserving the original text and transformation provenance.

The free-exercise profile selects the root record array and maps identity, name, category, primary muscles, and secondary muscles. Equipment, level, mechanic, instructions, force, and original category are retained inside provenance. Stretching records are excluded with a coded informational issue. No MET value is invented.

### Chinese Exercise Enrichment

Chinese exercise enrichment is a separate versioned JSON file keyed by the upstream source record ID:

```json
{
  "Barbell_Full_Squat": {
    "name_zh": "杠铃深蹲",
    "aliases": ["深蹲", "杠铃全蹲"],
    "pinyin": ["shendun", "gangling shendun"]
  }
}
```

The receiver validates duplicate definitions, invalid values, unknown source IDs, duplicate aliases, and orphaned enrichment rows. Missing enrichment does not block import: the canonical English name remains active and the report records an English fallback. Coverage is reported as a count and percentage.

### CatalogValidator

Validation has two levels:

- generic validation: required selectors, value presence, types, finite numbers, list shape, duplicate identity, and source metadata;
- catalog validation: food basis and four nutrients, supported exercise type, nonempty primary muscle, license/attribution, owner boundary, and provenance.

All source files are fully validated before the initial two-source script begins a database write.

### CatalogSink

`CatalogSink` adapts canonical records into the existing seed/import-ledger infrastructure. It does not issue ad hoc SQL from mapping profiles.

Each source import is atomic and independently retryable. Repeating one source/version/checksum is skipped. Reusing a completed source/version with a different checksum is rejected. Missing records within an actively managed source are deactivated. Explicit source retirement only affects public rows and search entries; private rows and immutable historical snapshots remain unchanged.

The first-version initial script imports the two sources independently after both validate. A database failure in one source rolls that source back and leaves the other source in a valid, retryable state.

## Error And Feedback Contract

Every issue has this shape:

```json
{
  "severity": "error",
  "code": "REQUIRED_VALUE_MISSING",
  "record": 37,
  "source_path": "foods[36].nutrients",
  "field": "protein",
  "observed": null,
  "expected": "non-negative number per 100g",
  "suggestion": "Map 粗蛋白/每100克含量 to protein"
}
```

Issue messages are derived from stable codes. The report includes canonical JSON Schema and one valid record example when a required field, mapping, or type is invalid.

File, syntax, dialect, mapping, and source-metadata errors fail immediately. Row-level validation continues across the file to produce complete counts, while detailed issue storage is capped at 1,000 entries. Any blocking issue prevents all writes for that source.

The CLI exit codes are:

| Code | Meaning |
|---:|---|
| 0 | Success |
| 2 | File or physical format error |
| 3 | Mapping profile error |
| 4 | Data validation error |
| 5 | Database import error |

## CLI

```powershell
python -m backend.tools.catalog_receiver inspect D:\data\20_2.csv

python -m backend.tools.catalog_receiver validate D:\data\20_2.csv `
  --mapping backend\data\catalog\mappings\tfda-foods.v1.json

python -m backend.tools.catalog_receiver import D:\data\20_2.csv `
  --mapping backend\data\catalog\mappings\tfda-foods.v1.json `
  --database backend\data\fitlife.sqlite3

python scripts\import_initial_catalogs.py `
  --foods D:\data\20_2.csv `
  --exercises D:\data\exercises.json `
  --exercise-aliases backend\data\catalog\enrichments\free-exercise-db.zh-CN.v1.json
```

The thin initial script selects the two built-in profiles and calls the same receiver service. It does not parse files or write SQL itself.

## Artifacts And Auditability

The operator can select an output directory. Each run writes:

- `catalog-import-report.json`;
- `catalog-import-report.txt`;
- `normalized-foods.json` when food normalization succeeds;
- `normalized-exercises.json` when exercise normalization succeeds.

Reports include original path basename, size, modification time, SHA-256, mapping version, source metadata, scanned/accepted/excluded/rejected counts, Chinese coverage, issue counts, database before/after counts, transaction result, and duration. Absolute source paths are not persisted in the database or logs.

Original files are not copied into the project. Normalized audit snapshots contain public catalog data only and no user data.

## File Layout

```text
backend/catalog_receiver/
  models.py
  readers.py
  inspector.py
  mapping.py
  projectors.py
  validators.py
  service.py
  sinks.py

backend/tools/catalog_receiver.py

backend/data/catalog/mappings/
  tfda-foods.v1.json
  free-exercise-db.v1.json

backend/data/catalog/enrichments/
  free-exercise-db.zh-CN.v1.json

scripts/import_initial_catalogs.py
```

Modules remain independently testable. Readers know physical files, mapping/projectors know source-to-canonical conversion, validators know canonical rules, and sinks know persistence. No module other than the sink depends on SQLite.

## Testing

### Unit Tests

- UTF-8, UTF-8 BOM, quoting, embedded newlines, configured delimiters, ambiguous dialects, duplicate headers, invalid encodings, and missing files;
- JSON root arrays, nested arrays, ambiguous record arrays, invalid JSON, missing selectors, and size limits;
- unambiguous mapping suggestions and mandatory rejection of ambiguity;
- allow-listed transformation behavior and rejection of executable or unknown operations;
- grouped Taiwan food projection and all four nutrient pivots;
- inconsistent grouped descriptors, duplicate IDs, missing nutrients, invalid numbers, and unsupported units;
- free-exercise category mapping, stretching exclusion, muscles, provenance, and English fallback;
- enrichment merge, duplicate names, invalid pinyin, unknown IDs, orphan rows, and coverage reports;
- stable issue codes, source locations, suggestions, canonical examples, detail cap, and CLI exit codes.

### Integration Tests

- repeated source/version/checksum imports create no duplicates;
- completed source/version checksum drift is rejected;
- one bad canonical record rolls the source import back;
- source retirement affects public rows and FTS only;
- user custom rows and historical snapshots remain unchanged;
- Simplified Chinese, Traditional Chinese, English, alias, and pinyin searches resolve expected foods;
- English and available Chinese aliases resolve expected exercises;
- the initial two-source script validates both files before its first write and can be rerun safely.

### Real-Data Acceptance

- the audited Taiwan file yields 2,181 foods;
- every accepted food has calories, carbohydrates, protein, fat, license, attribution, and provenance;
- the free-exercise report shows the audited category distribution or explicitly reports upstream drift;
- all 123 audited stretching records are excluded rather than misclassified;
- compatible records import with Chinese enrichment where available and English fallback elsewhere;
- malformed fixtures produce actionable reports and zero writes;
- the second identical run is skipped by the import ledger;
- existing demonstration public sources retire without altering private or historical data.

## Success Criteria

- An unfamiliar local CSV or JSON file can be inspected without writes and receives a mapping draft or a precise ambiguity report.
- Missing canonical fields always identify the source location, expected type, correction guidance, canonical schema, and valid example.
- The two approved public files can be validated and imported through one shared receiver and two declarative profiles.
- No Agent, network request, URL input, arbitrary code execution, or user-facing import endpoint is involved.
- Import failures are atomic, observable, retryable, and preserve the last usable catalog state.
- The design extends to later CSV/JSON sources by adding profiles and bounded transforms rather than duplicating ingestion pipelines.
