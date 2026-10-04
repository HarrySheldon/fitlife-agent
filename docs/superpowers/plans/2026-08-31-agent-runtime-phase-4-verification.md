# Phase 4 verification (in progress)

Implementation remains confined to `.worktrees/agent-runtime-refactor` on
`codex/agent-runtime-refactor`; main checkout changes are not part of this work.

## Implemented seams

- Strict configuration models, atomic in-memory policy revision publication,
  last-known-good retention, immutable effective policy snapshots and bounded
  secret-free operator diagnostics.
- Shared process-local user/anonymous rate and concurrency admission. Evaluation
  batch admission consumes a rate slot, while each child run owns a concurrency
  slot; batch case count is checked before any case starts.
- Mandatory input and output safety gates. Rule-based screening is a conservative
  baseline, not a clinical classifier. Additional reviewer metadata is restricted
  to known risk codes and controlled disclaimers; unavailable review cannot return
  an unreviewed draft.
- Plan adjustment and Smart Entry structured suggestions now use the same Runtime
  factory as chat/coach. Unsafe structured output is refused because a prose
  fallback cannot replace a validated plan or nutrition object. Business writes
  remain in deterministic use cases after reviewed model completion.
- Coach context loading runs inside a Runtime step. Its failures now have run and
  request identity, and its work is covered by admission and deadline control.

## Evidence recorded on 2026-09-12

All commands use `D:/code/vibe-coding/fitlife-agent/.venv/Scripts/python.exe -m pytest`
from the isolated worktree, with distinct worktree-local `--basetemp` directories.
Tests use fake gateways and do not request paid model tokens.

- `test_structured_runtime.py test_eval.py test_agent_graph.py
  application/test_plans.py application/test_smart_entry_analysis.py`: **48 passed**,
  exit 0 (`.tmp/phase4_entrances_0912c`). Covers actual structured Runtime execution,
  retries, deadline, unsafe output refusal, context-loader failure identity, and
  unchanged deterministic draft/activation behavior.
- `test_smart_entry_api.py test_smart_entry_confirmation.py test_coach_api.py
  test_agent_runtime_workflow.py test_agent_safety.py`: **25 passed, 1 failed**
  (`.tmp/phase4_api_0912d`). Failure was the old exact workflow step list omitting
  the newly required `safety_reviewer`; corrected by the workflow implementer,
  with revalidation still required before acceptance.
- Evaluation admission/API tests expanded afterward: **8 passed**, exit 0
  (`.tmp/eval_admission_0912`). Includes authenticated owner propagation and batch
  rate/case-cap rejection before case execution.
- Safety review additions first reproduced **3 failures, 12 passes**; after the
  controlled metadata and explicit scope rules, **15 passed**, exit 0
  (`.tmp/safety_review_green_0912`). Independent specification re-review also
  reported **15 passed** and accepted both corrections.

## Outstanding acceptance

Independent phase-4 specification review found no confirmed execution-policy
defects. The unused `DeploymentSettings` subclass was removed; the existing
static `Settings` loader retains its `.env` compatibility while dynamic policies
remain strict. Independent quality review requested two corrections before
acceptance: eliminate unnecessary user-connection discovery I/O before deadline
creation, and apply effective completed-run retention instead of legacy defaults.
Both corrections are now implemented: policy resolution has no connection
discovery callback or I/O, and all completion paths pass effective retention to
cache eviction. Four new regressions cover zero retention from deployment and
publication on success/failure, while SQLite history stays queryable. The main
agent independently ran **55 tests**, exit 0 in **2.92 seconds**
(`.tmp/phase4_fixed_acceptance`). Independent correction re-review approved both
fixes after 20 configuration tests. A further main-agent expanded regression
passed 238 tests, 892 deselected, exit 0 (`.tmp/phase4_postreview_broad`).

Full backend checkpoint command (`backend/tests -q --tb=line
--basetemp=.tmp/phase4_full_checkpoint`) completed with **1125 passed**, one
Starlette/httpx deprecation warning, exit 0 in **511.86 seconds**. This command
started before the two quality-review corrections; their targeted revalidation
and final post-phase-5 full-suite run remain required.

Resume verification: the combined configuration, rate, safety, structured,
workflow, deadline, persistence, runtime-quality, evaluation, graph and plan/
Smart Entry regression passed **133 tests**, exit 0
(`.tmp/phase4_acceptance_resume`). The broader Agent/chat/coach/runtime/model/eval
selection passed **219 tests**, 905 deselected, exit 0
(`.tmp/phase4_broad_resume`). This also revalidates the corrected step-order tests.
An additional unvalidated-reviewer-model bypass was reproduced and corrected by
forcing instance revalidation at the reviewer boundary; safety now has **16
passing tests** (`.tmp/safety_construct_green`).

Persisted configuration snapshots contain only execution `policy` and `revision`.
User connection metadata is not a binding until the gateway is resolved; actual
provider/model is recorded in separate run columns. Each workflow resolves its
gateway once and reuses that object; a provider-reported resolved model name may
replace its configured alias in diagnostic metadata without switching connections.

Phase-4 specification, quality and correction reviews are complete; phase 5 is
underway. The complete backend suite must still be rerun after phase 5 for final
acceptance; the earlier full-suite checkpoint does not verify later changes.
