# Evaluation v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade FitLife Agent evaluation from coarse booleans to structured, deterministic case checks with failure reasons and grouped metrics.

**Architecture:** `backend/evaluation.py` remains the single evaluation runner used by the CLI and API. Each eval case is scored by a small set of local graders derived from expected tool, retrieval source, answer format, keywords, and validator state; aggregate metrics keep the existing keys and add grouped summaries for analysis.

**Tech Stack:** Python stdlib, pytest, existing LangGraph-backed agent runner.

---

## References

- OpenAI evaluation guidance: define representative test data, explicit testing criteria, and repeatable graders; analyze failures by category before iterating.
- Existing project contract: `run_evaluation(limit)` returns old metric keys and writes `backend/data/eval_results.json`.

## Acceptance Criteria

- Evaluation remains deterministic and runnable without network access or API keys.
- Each case includes a `checks` list with check name, pass/fail status, expected value, observed value, and reason.
- Each failed case includes `failure_reasons`.
- Existing result keys remain present: `pass_rate`, `tool_call_success_rate`, `retrieval_hit_rate`, `structured_output_success_rate`, `preference_compliance_rate`, `validator_pass_rate`, `failed_cases`, and `cases`.
- The summary adds grouped metrics by expected tool and retrieval requirement.
- `backend/data/eval_results.json` is still written.
- A Markdown summary artifact is written to `backend/data/eval_results.md` for quick review.
- Backend tests and a 5-case eval smoke run pass.

## Files

- Modify: `backend/evaluation.py`
  - Add local check construction.
  - Add failure reason collection.
  - Add grouped metrics.
  - Persist JSON and Markdown artifacts.
- Modify: `.gitignore`
  - Ignore the Markdown eval artifact.
- Test: `backend/tests/test_eval.py`
  - Assert structured checks and failure reasons.
  - Assert grouped metrics.
  - Assert JSON and Markdown artifacts are written.

## TDD Steps

1. Write failing eval tests in `backend/tests/test_eval.py`.
2. Run `..\..\.venv\Scripts\python -m pytest backend\tests\test_eval.py -q -p no:cacheprovider` and verify failures are due to missing Evaluation v2 fields.
3. Implement minimal structured checks and failure reasons in `backend/evaluation.py`.
4. Run the targeted eval tests and verify they pass.
5. Add grouped metrics and Markdown artifact generation.
6. Run the targeted eval tests again.
7. Run full backend tests:

```powershell
..\..\.venv\Scripts\python -m pytest backend\tests -q -p no:cacheprovider
```

8. Run eval smoke:

```powershell
..\..\.venv\Scripts\python scripts\run_eval.py --limit 5
```

9. Commit and push `feat/evaluation-v2`.
