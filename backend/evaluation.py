"""Bounded evaluation batches with safe scoring projections."""
from __future__ import annotations
import hashlib
import json
import os
import re
from threading import RLock
from uuid import uuid4

from backend.agent.contracts import AgentCommand
from backend.agent.graph import _LazyFitLifeWorkflow
from backend.agent.failures import classify_failure
from backend.agent.persistence import ERROR_CODES, utc_now
from backend.agent.runtime import BudgetExceeded, RunTimedOut
from backend.domain.user_preferences import UserPreferences
from backend.infrastructure.agent_runtime import factory
from backend.infrastructure.model_gateway.evaluation_mock import EvaluationMockGateway
from backend.schemas import EvalCase
from backend.tools.data_access import data_path, read_eval_cases

_ARTIFACT_LOCK = RLock()
_TOOLS = frozenset({"load_profile", "analyze_meals", "analyze_workouts", "retrieve_knowledge",
                    "generate_weekly_report", "generate_next_week_plan", "validate_plan"})
_METRICS = {"tool_ok": "tool_call", "retrieval_ok": "retrieval", "keywords_ok": "keywords",
            "structured_ok": "answer_format", "validator_ok": "validator"}


def run_fitlife_agent(question, *, operation, request_id, user_id, gateway, request_overrides):
    """Fresh case admission and run in the same shared factory runtime."""
    command = AgentCommand(operation=operation, question=question, user_id=user_id,
                           request_id=request_id, request_overrides=request_overrides)
    workflow = _LazyFitLifeWorkflow(None, gateway, user_id, UserPreferences())
    return factory.get_agent_runtime().execute_sync(command, workflow).to_dict()


def run_evaluation(limit: int | None = None, request_id: str | None = None,
                   user_id: str | None = None, execution_mode: str = "live") -> dict:
    if execution_mode not in {"mock", "live"}:
        raise ValueError("Evaluation mode must be mock or live")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("Evaluation limit must be a positive integer")
    # Validate the entire dataset, including cases excluded by limit.
    cases = [EvalCase.model_validate(case.model_dump() if isinstance(case, EvalCase) else case)
             for case in read_eval_cases()]
    dataset_hash = hashlib.sha256(json.dumps([case.model_dump() for case in cases],
                                            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    cases = cases if limit is None else cases[:limit]
    request_id = request_id or uuid4().hex
    runtime = factory.get_agent_runtime()
    config = runtime.resolver.resolve("evaluation", user_id)
    if len(cases) > config.policy.evaluation.max_cases:
        raise BudgetExceeded("The evaluation case budget was exceeded.", request_id=request_id)
    # Live selection belongs inside each admitted run's deadline.
    gateway = EvaluationMockGateway() if execution_mode == "mock" else None
    with runtime.limiter.acquire(user_id, config.policy.rate_limit, concurrent=False):
        _preflight_artifacts()
        return _run_cases(cases, request_id, user_id, execution_mode, gateway, config, dataset_hash)


def _run_cases(cases, request_id, user_id, mode, gateway, config, dataset_hash):
    started_at, batch_id = utc_now(), uuid4().hex
    limits, case_budget = config.policy.evaluation, config.policy.budget
    reserved_calls = reserved_tokens = 0
    results = []
    provider = gateway.provider if getattr(gateway, "provider", None) in {"openai", "custom", "mock"} else None
    model = getattr(gateway, "model", None)
    model = model if isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,100}", model) and not model.startswith(("sk-", "http")) else None
    metadata = {"execution_mode": mode, "provider": provider, "model": model,
                "prompt_version": "deterministic-v1" if mode == "mock" else "fitlife-prompts-v1",
                "policy_version": f"policy-{config.revision}", "dataset_hash": dataset_hash}
    for index, case in enumerate(cases, 1):
        case_request_id = uuid4().hex
        item = {"case_id": uuid4().hex, "display_label": f"Case {index}",
                "question": f"Case {index}",  # Legacy UI label, never raw input.
                "expected_tool": case.expected_tool if case.expected_tool in _TOOLS else "other" if case.expected_tool else None,
                "expected_retrieval_doc": "required" if case.expected_retrieval_doc else None,
                "passed": False, "case_status": "skipped", "error_code": "RUN_BUDGET_EXCEEDED",
                "checks": [], "failure_reasons": ["Batch budget exhausted."],
                "request_id": case_request_id, "batch_request_id": request_id, "batch_run_id": batch_id,
                "run_id": None, "started_at": None, "finished_at": None, **metadata,
                "policy_version": None, "provider": None, "model": None,
                "provenance_status": "unavailable",
                **{key: False for key in _METRICS}}
        results.append(item)
        # Reserve the whole run allowance including retries; no refund because
        # a timed-out worker may still finish after the caller has returned.
        if reserved_calls + case_budget.max_model_calls > limits.max_model_calls or reserved_tokens + case_budget.max_tokens > limits.max_tokens:
            continue
        reserved_calls += case_budget.max_model_calls
        reserved_tokens += case_budget.max_tokens
        item["started_at"] = utc_now()
        response = None
        try:
            response = run_fitlife_agent(case.question, operation="evaluation", request_id=case_request_id,
                user_id=user_id, gateway=gateway, request_overrides={"max_model_calls": case_budget.max_model_calls,
                                                                   "max_tokens": case_budget.max_tokens})
            item["run_id"] = response.get("run_id")
            checks = _build_case_checks(case, response.get("trace", {}), response.get("answer_markdown", ""))
            passed = all(check["passed"] for check in checks)
            scores = {check["name"]: check["passed"] for check in checks}
            item.update(passed=passed, case_status="passed" if passed else "failed", error_code=None,
                        checks=checks, run_id=response.get("run_id"),
                        failure_reasons=[check["reason"] for check in checks if not check["passed"]],
                        **{key: scores[name] for key, name in _METRICS.items()})
        except Exception as error:
            code = getattr(error, "code", None) or classify_failure(error, stage="evaluation", attempt=1).code
            item.update(case_status="timed_out" if isinstance(error, RunTimedOut) else "error",
                        error_code=code if code in ERROR_CODES else "INTERNAL_ERROR",
                        run_id=getattr(error, "run_id", None) or item["run_id"], failure_reasons=["Case execution failed."])
        finally:
            item["finished_at"] = utc_now()
            if item["run_id"]:
                try:
                    snapshot = factory.get_agent_runtime().repository.get(item["run_id"], user_id)
                    item.update(policy_version=snapshot.policy_version, provider=snapshot.provider,
                                model=snapshot.model, started_at=snapshot.started_at or snapshot.created_at,
                                finished_at=snapshot.finished_at or item["finished_at"],
                                provenance_status="available")
                except Exception:
                    # Adapter failures must not abort other cases or turn an
                    # unverified result into a reported success. Keep any
                    # original execution error; never expose storage details.
                    if item["case_status"] not in {"error", "timed_out"}:
                        item.update(case_status="error", error_code="INTERNAL_ERROR")
                    item.update(passed=False, checks=[],
                                failure_reasons=[*item["failure_reasons"], "Run provenance unavailable."],
                                **{key: False for key in _METRICS})
    metric = lambda key: _rate([item[key] for item in results])
    output = {"request_id": request_id, "run_id": batch_id, **metadata,
        "started_at": started_at, "finished_at": utc_now(), "total_tests": len(results),
        "pass_rate": metric("passed"), "tool_call_success_rate": metric("tool_ok"),
        "retrieval_hit_rate": metric("retrieval_ok"), "structured_output_success_rate": metric("structured_ok"),
        "preference_compliance_rate": metric("keywords_ok"), "validator_pass_rate": metric("validator_ok"),
        "budget": {"accounting": "reserved_per_case_maximum", "reserved_model_calls": reserved_calls,
                   "reserved_tokens": reserved_tokens, "max_model_calls": limits.max_model_calls, "max_tokens": limits.max_tokens},
        "group_metrics": _group_metrics(results), "failed_cases": [item for item in results if not item["passed"]], "cases": results}
    _persist(output)
    return output


def _build_case_checks(case, trace: dict, answer: str) -> list[dict]:
    scores = {
        "tool_call": not case.expected_tool or case.expected_tool in trace.get("tool_calls", []),
        "retrieval": not case.expected_retrieval_doc or case.expected_retrieval_doc in trace.get("retrieved_sources", []),
        "keywords": all(keyword in answer for keyword in case.expected_keywords),
        "answer_format": "##" in answer if case.expected_answer_format == "markdown" else True,
        "validator": bool(trace.get("validation_passed", True)),
    }
    return [{"name": name, "passed": bool(passed), "reason": f"{name} check {'passed' if passed else 'failed'}."}
            for name, passed in scores.items()]


def _group_metrics(results):
    return {"by_expected_tool": _group_by(results, lambda item: item["expected_tool"] or "none"),
            "by_retrieval_requirement": _group_by(results, lambda item: "requires_retrieval" if item["expected_retrieval_doc"] else "no_retrieval_expected")}


def _group_by(results, key_fn):
    grouped = {}
    for item in results:
        grouped.setdefault(key_fn(item), []).append(item)
    return {key: {"total": len(items), "pass_rate": _rate([item["passed"] for item in items])}
            for key, items in sorted(grouped.items())}


def _persist(output):
    serialized = json.dumps(output, ensure_ascii=False, indent=2)
    markdown = _format_markdown_summary(output)
    # Immutable batch artifacts survive concurrent runs. Compatibility files are
    # replaced atomically so readers cannot observe partially written JSON.
    directory = data_path("eval_runs") / output["run_id"]
    directory.mkdir(parents=True, exist_ok=False)
    _atomic_write(directory / "eval_results.json", serialized)
    _atomic_write(directory / "eval_results.md", markdown)
    with _ARTIFACT_LOCK:
        _atomic_write(data_path("eval_results.json"), serialized)
        _atomic_write(data_path("eval_results.md"), markdown)


def _preflight_artifacts():
    """Check both artifact destinations without replacing any existing report."""
    for directory in (data_path("eval_results.json").parent, data_path("eval_runs")):
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".eval-probe-{uuid4().hex}.tmp"
        try:
            with probe.open("x", encoding="utf-8") as stream:
                stream.write("evaluation storage probe")
        finally:
            probe.unlink(missing_ok=True)


def _atomic_write(path, content):
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _format_markdown_summary(output):
    lines = ["# FitLife Agent Evaluation", "", f"- Mode: {output['execution_mode']}",
             f"- Run: {output['run_id']}", f"- Total tests: {output['total_tests']}",
             f"- Pass rate: {output['pass_rate']}", "", "## Failed Cases", ""]
    lines.extend(f"- {item['display_label']}: {item['case_status']} ({item['error_code'] or 'CHECK_FAILED'})" for item in output["failed_cases"])
    return "\n".join(lines) + "\n"


def _rate(values):
    return round(sum(bool(value) for value in values) / len(values), 4) if values else 0
