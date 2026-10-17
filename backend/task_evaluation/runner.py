"""Runner: execute a scenario against an isolated public API.

Every scenario runs against its own data directory and its own registered user. A
Provider stub raises immediately on any network attempt, so a mock run can only ever
touch local seeded data. The runner returns a desensitised result: no raw user input,
no credentials, no exception text beyond a controlled classification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4
import multiprocessing
import time
import tempfile
from urllib.parse import quote
from dataclasses import replace

from backend.task_evaluation.scorers import score_state


class CaseError(Exception):
    """A scenario cannot be executed as written - a script bug, not a product result."""


class UnexpectedQuestion(Exception):
    """The API asked for a field the scenario did not script an answer for."""


class NetworkAttempt(AssertionError):
    """The mock gateway was asked to reach a provider. It must never be."""


def reject_nonempty_workspace(root: Path) -> None:
    """A workspace must be created for the run, never pointed at real data."""
    if root.exists():
        entries = [p for p in root.iterdir()]
        if entries:
            raise CaseError(
                f"Refusing to use an existing non-empty directory as an evaluation workspace: {root}"
            )


class ScriptedGateway:
    """A gateway that answers deterministic questions and refuses the network."""

    provider = "mock"
    model = "task-eval-scripted-v1"

    def __getattr__(self, name: str):
        if name.startswith("parse_") or name in {"plan_route", "write_answer"}:
            def refuse(*args, **kwargs):
                raise NetworkAttempt(f"Scripted gateway cannot call {name}")
            return refuse
        raise AttributeError(name)


@dataclass(frozen=True)
class StepResult:
    path: str
    status: int
    captured: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CaseResult:
    scenario_id: str
    version: int
    status: str  # passed | failed | case_error | unexpected_question
    observed: dict[str, object] = field(default_factory=dict)
    failures: tuple[str, ...] = field(default=())
    steps: tuple[StepResult, ...] = field(default=())
    metrics: dict[str, object] = field(default_factory=dict)


def _resolve(reference: str, variables: dict[str, object]):
    """Resolve a ``{name}`` or ``name`` reference against captured variables."""
    if isinstance(reference, dict):
        if set(reference) == {"$ref"}:
            name = reference["$ref"]
            if name not in variables:
                raise CaseError("Unknown reference")
            return variables[name]
        return {key: _resolve(value, variables) for key, value in reference.items()}
    if isinstance(reference, list):
        return [_resolve(value, variables) for value in reference]
    if not isinstance(reference, str):
        return reference
    text = str(reference)
    if text.startswith("{") and text.endswith("}"):
        name = text[1:-1]
        if name not in variables:
            raise CaseError(f"Variable reference {name!r} was never captured")
        return variables[name]
    return text


def _render_path(path: str, variables: dict[str, object]) -> str:
    parts = []
    rest = path
    while "{" in rest:
        head, bracket, tail = rest.partition("{")
        parts.append(head)
        name, _, tail = tail.partition("}")
        if name not in variables:
            raise CaseError(f"Variable reference {name!r} in {path!r} was never captured")
        value = variables[name]
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise CaseError("Invalid path reference")
        parts.append(quote(str(value), safe=""))
        rest = tail
    parts.append(rest)
    rendered = "".join(parts)
    from backend.task_evaluation.contracts import Step
    Step.local_path(rendered)
    return rendered


def _capture(payload: dict, fields: dict[str, str], variables: dict[str, object]) -> dict[str, object]:
    captured: dict[str, object] = {}
    for variable, field_path in fields.items():
        value = _response_value(payload, field_path)
        captured[variable] = value
        variables[variable] = value
    return captured


def _response_value(payload, path):
    parts = path.split(".")
    if len(parts) > 20:
        raise CaseError("Response path exceeds maximum depth")
    value = payload
    for key in parts:
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and key.isascii() and key.isdecimal() and len(key) <= 3 and int(key) < len(value):
            value = value[int(key)]
        else:
            raise CaseError("Response path is missing or invalid")
    return value


def _observe_response(payload, mapping):
    """Only closed business metadata can enter a desensitized report."""
    import re
    integers = (r"data\.(version|remaining_draft_version)",
                r"data\.payload\.interaction\.clarification_rounds",
                r"data\.payload\.interaction\.items\.[0-9]{1,3}\.revision")
    enums = {
        r"data\.payload\.interaction\.status": {'collecting', 'awaiting_clarification', 'awaiting_confirmation', 'partially_saved', 'completed', 'cancelled', 'expired'},
        r"data\.payload\.interaction\.items\.[0-9]{1,3}\.state": {'needs_clarification', 'ready', 'saved', 'discarded'},
        r"data\.(item_commits|commits)\.[0-9]{1,3}\.record_state": {'unchanged', 'changed', 'deleted'},
    }
    result = {}
    for key, path in mapping.items():
        value = _response_value(payload, path)
        if any(re.fullmatch(pattern, path) for pattern in integers):
            valid = type(value) is int and 0 <= value <= 1_000_000
        elif path == 'data.replayed':
            valid = type(value) is bool
        else:
            allowed = next((values for pattern, values in enums.items() if re.fullmatch(pattern, path)), None)
            valid = allowed is not None and isinstance(value, str) and value in allowed
        if not valid:
            raise CaseError("Response observation is not allowed metadata")
        result[key] = value
    return result


def execute_scenario(scenario, client, *, headers_factory, observer=None, before_step=None, progress_metrics=None, supported_capabilities=frozenset()) -> CaseResult:
    """Run one scenario's steps in-process against a TestClient.

    ``headers_factory`` returns the auth headers for the scenario's user. The runner
    itself holds no opinion about how the client and environment were built; that is
    the caller's isolation duty.
    """
    variables: dict[str, object] = {}
    observed: dict[str, object] = {}
    steps: list[StepResult] = []
    processing_ms = 0.0
    business_started = None
    candidate_ms = None
    first_candidate = None
    confirmed_candidate = None
    valid_candidates = {}
    confirmations = {}
    response_ready_ms = None
    snapshots = {}
    def incomplete(status, failures):
        if observer:
            observed.update(observer())
        return CaseResult(scenario.id, scenario.version, status, observed=observed,
                          failures=failures, steps=tuple(steps), metrics={"processing_ms": processing_ms,
                          "candidate_ms": candidate_ms, "first_candidate": first_candidate, "confirmed_candidate": confirmed_candidate,
                          "candidate_reason": "no_verified_candidate" if candidate_ms is None else "validated_candidate"})
    if not set(scenario.requires).issubset(supported_capabilities):
        return CaseResult(scenario.id, scenario.version, "unsupported", failures=("requires",))

    for step in scenario.steps:
        path = _render_path(step.path, variables)
        if before_step:
            before_step(step)
        body = _resolve(step.body or {}, variables)
        if step.answer_by_field and path.endswith('/interaction/answers'):
            resource_path = path.removesuffix('/interaction/answers')
            snapshot = snapshots.get((step.actor, resource_path))
            groups = snapshot.get('payload', {}).get('interaction', {}).get('question_groups', []) if snapshot else []
            pending = [group for group in groups if group.get('answered') is False]
            if len(pending) != 1:
                return incomplete('unexpected_question', ('no_pending_questions',))
            group = pending[0]
            scripted = _resolve(step.answer_by_field, variables)
            if any(question['field'] not in scripted for question in group['questions']):
                return incomplete('unexpected_question', ('unscripted_field',))
            body = {'expected_version': snapshot['version'], 'question_group_id': group['group_id'],
                    'answers': [{'item_id': question['item_id'], 'field': question['field'],
                                 'value': scripted[question['field']]} for question in group['questions']]}
        try:
            headers = dict(headers_factory(step.actor))
        except TypeError:
            if step.actor != "primary":
                raise CaseError("Actor-aware authentication required")
            headers = dict(headers_factory())
        for key, value in step.headers.items():
            headers[key] = str(_resolve(value, variables))
        request_started = time.monotonic()
        if business_started is None:
            business_started = request_started
        try:
            response = client.request(step.method, path, headers=headers, json=body or None)
        finally:
            processing_ms += (time.monotonic() - request_started) * 1000
            if progress_metrics is not None:
                progress_metrics["processing_ms"] = processing_ms
        captured = {}
        payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if response.status_code == 200 and isinstance(data.get('id'), str) and isinstance(data.get('payload'), dict):
            snapshots[(step.actor, '/api/v1/smart-entry-drafts/' + data['id'])] = data
        candidates = data.get("payload", {}).get("candidates", []) if isinstance(data.get("payload"), dict) else []
        if response.status_code == 200 and candidates:
            from backend.infrastructure.repositories.sqlite_smart_entry_repository import _candidate, _validate_selected_candidates
            try:
                selected = tuple(_candidate(item) for item in candidates if isinstance(item, dict) and item.get("selected"))
                _validate_selected_candidates(selected)
                import re
                resource_id = data.get("id")
                version = data.get("version")
                if not isinstance(resource_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", resource_id) or type(version) is not int or version <= 0:
                    raise ValueError("Invalid candidate identity")
            except Exception:
                pass
            else:
                identity = {"id": resource_id, "version": version, "actor": step.actor, "kind": "smart_entry"}
                valid_candidates[(resource_id, version, step.actor)] = identity
                if candidate_ms is None:
                    candidate_ms = (time.monotonic() - business_started) * 1000
                    first_candidate = identity
                    if progress_metrics is not None:
                        progress_metrics["candidate_ms"] = candidate_ms
                        progress_metrics["first_candidate"] = first_candidate
        if response.status_code == 200 and path.endswith("/confirm"):
            matched_version = headers.get("If-Match", "")
            response_id = data.get("draft_id")
            if matched_version.isdigit() and isinstance(response_id, str) and path.endswith("/" + response_id + "/confirm"):
                confirmed_candidate = valid_candidates.get((response_id, int(matched_version), step.actor))
                if progress_metrics is not None:
                    progress_metrics["confirmed_candidate"] = confirmed_candidate
            key = (step.actor, path, headers.get("Idempotency-Key"))
            ids = {field: data.get(field) for field in ("meal_ids", "training_session_ids", "workout_ids")}
            if key in confirmations:
                observed["replay_verified"] = ids == confirmations[key] and any(ids.values())
            confirmations[key] = ids
        validation = data.get("plan", {}).get("validation", {}) if isinstance(data.get("plan"), dict) else {}
        if candidate_ms is None and validation.get("passed") is True and not validation.get("violations"):
            candidate_ms = (time.monotonic() - business_started) * 1000
            import re
            plan_id = data.get("draft_id")
            first_candidate = {"id": plan_id if isinstance(plan_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", plan_id) else None, "actor": step.actor, "kind": "plan"}
        if path in {"/chat", "/coach/action"}:
            observed["answer_nonempty"] = observed.get("answer_nonempty", True) and isinstance(data.get("answer_markdown"), str) and bool(data["answer_markdown"].strip())
            observed["response_has_run_id"] = observed.get("response_has_run_id", True) and isinstance(data.get("run_id"), str) and bool(data["run_id"])
            if response.status_code == 200 and observed["answer_nonempty"] and observed["response_has_run_id"] and response_ready_ms is None:
                response_ready_ms = (time.monotonic() - business_started) * 1000
        missing = payload.get("data", {}).get("missing_fields", []) if isinstance(payload.get("data"), dict) else []
        if missing:
            names = [item.get("name", item.get("field")) if isinstance(item, dict) else item for item in missing]
            status = "unexpected_question" if any(name not in step.answer_by_field for name in names) else "unsupported"
            return incomplete(status, ("missing_fields",))
        if step.answer_by_field and not path.endswith('/interaction/answers'):
            return incomplete("unsupported", ("answer_flow",))
        steps.append(StepResult(path=step.path, status=response.status_code))
        if step.expected_status is not None and response.status_code != step.expected_status:
            return incomplete("failed", ("unexpected_status",))
        if step.capture:
            _capture(payload, step.capture, variables)
        if step.observe:
            observed.update(_observe_response(payload, step.observe))

    if observer:
        observed.update(observer())
    score = score_state(scenario.expected, observed)
    return CaseResult(
        scenario_id=scenario.id,
        version=scenario.version,
        status="passed" if score.passed else "failed",
        observed=observed,
        failures=() if score.passed else score.failed_fields,
        steps=tuple(steps),
        metrics={"processing_ms": processing_ms, "candidate_ms": candidate_ms,
                 "first_candidate": first_candidate, "confirmed_candidate": confirmed_candidate,
                 "response_ready_ms": response_ready_ms,
                 "candidate_reason": "validated_candidate" if candidate_ms is not None else "no_verified_candidate"},
    )


def run_isolated_scenario(scenario, *, deadline, budget=None) -> CaseResult:
    """Spawn a private worker; deadline is an absolute monotonic timestamp."""
    from backend.task_evaluation.worker import worker_main
    if budget is None:
        from backend.task_evaluation.budget import BatchBudget
        budget = BatchBudget(200, 200000)
    started = time.monotonic()
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=True)
    workspace = tempfile.TemporaryDirectory(prefix="fitlife-task-eval-")
    process = context.Process(target=worker_main, args=(child, scenario.model_dump(mode="json", exclude_unset=True), workspace.name))
    outcome = None
    cleanup_status = "completed"
    owned_reservations = set()
    try:
        process.start()
        child.close()
        while time.monotonic() < deadline:
            if parent.poll(min(0.05, max(0, deadline - time.monotonic()))):
                try:
                    result = parent.recv()
                except EOFError:
                    break
                if isinstance(result, dict) and result.get("rpc") in {"reserve", "settle"}:
                    try:
                        if result["rpc"] == "reserve":
                            if set(result) != {"rpc", "upper_bound", "token_upper_bound"}:
                                raise ValueError("Invalid RPC")
                            reservation = budget.reserve(result["upper_bound"], result["token_upper_bound"]) if budget else True
                            if reservation:
                                owned_reservations.add(reservation)
                            parent.send({"ok": bool(reservation), "reservation": reservation})
                        else:
                            if budget:
                                if set(result) != {"rpc", "reservation", "usage", "token_usage"}:
                                    raise ValueError("Invalid RPC")
                                if result["reservation"] not in owned_reservations:
                                    raise ValueError("Invalid reservation owner")
                                budget.settle(result["reservation"], result["usage"], result["token_usage"])
                            parent.send({"ok": True})
                    except Exception:
                        parent.send({"ok": False})
                    continue
                if not isinstance(result, CaseResult):
                    break
                outcome = replace(result, metrics={**result.metrics, "elapsed_ms": round((time.monotonic() - started) * 1000), "ledger": budget.snapshot() if budget else None})
                break
            if not process.is_alive():
                break
        status = "deadline_exceeded" if time.monotonic() >= deadline else "worker_error"
        if outcome is None:
            outcome = CaseResult(scenario.id, scenario.version, status, failures=(status,), metrics={"elapsed_ms": round((time.monotonic() - started) * 1000), "ledger": budget.snapshot() if budget else None})
    except Exception:
        outcome = CaseResult(scenario.id, scenario.version, "worker_error", failures=("worker_error",), metrics={"ledger": budget.snapshot(), "elapsed_ms": round((time.monotonic() - started) * 1000)})
    finally:
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join()
            process.close()
        parent.close()
        child.close()
        try:
            workspace.cleanup()
        except OSError:
            cleanup_status = "failed"
    return replace(outcome, metrics={**outcome.metrics, "cleanup_status": cleanup_status})


def to_run_record(result: CaseResult, *, mode: str, git_sha: str | None = None,
                  config_fingerprint: str | None = None):
    """Map a case result to a provenance-bearing report record.

    Successful mock calls carry character estimates, labelled separately from
    provider usage. Failed and interrupted calls retain unknown total usage.
    """
    from backend.task_evaluation.report import RunRecord
    from backend.task_evaluation.provenance import source_digest, prompt_digest, fingerprint
    passed = result.status == "passed" and result.metrics.get("cleanup_status") != "failed"
    return RunRecord(
        mode=mode,
        case_id=result.scenario_id,
        version=result.version,
        success=passed,
        total_tokens=result.metrics.get("estimated_tokens"),
        model=result.metrics.get("model"),
        rule_version=result.metrics.get("rule_version"),
        git_sha=git_sha,
        workspace_diff=source_digest(),
        prompt_version=prompt_digest(),
        config_fingerprint=fingerprint({"batch": config_fingerprint, "worker": result.metrics.get("safe_config_fingerprint"), "policy": result.metrics.get("policy_version"), "policy_config": result.metrics.get("policy_config_digest")}),
        candidate_ms=result.metrics.get("candidate_ms"),
        processing_ms=result.metrics.get("processing_ms"),
        calls=result.metrics.get("gateway_attempts"),
        retries=result.metrics.get("retries"),
        details={key: value for key, value in result.metrics.items() if key in {"run_ids", "ledger", "elapsed_ms", "provider_usage", "mock_usage_estimated", "policy_version", "rule_pack_version", "candidate_reason", "token_measurement", "cleanup_status", "dataset_hash", "catalog_digest", "known_estimated_tokens", "failed_attempts", "started_at", "finished_at", "first_candidate", "confirmed_candidate"}},
        error_class=None if passed else "cleanup_failed" if result.metrics.get("cleanup_status") == "failed" else result.status,
    )


# Statuses that are a definite outcome for a case. Anything else is an infrastructure
# problem and must not be silently counted as a finished case.
DEFINITE_STATUSES = frozenset({"passed", "failed", "unsupported"})


def run_suite(scenarios, *, mode, deadline, budget, git_sha=None, config_fingerprint=None):
    """Run every scenario against the shared batch budget and one absolute deadline.

    Cases after the deadline are recorded as deadline_exceeded without spawning, so a
    single slow case cannot consume the whole batch's allowance.
    """
    records = []
    for scenario in scenarios:
        if time.monotonic() >= deadline:
            result = CaseResult(scenario.id, scenario.version, "deadline_exceeded", failures=("deadline_exceeded",))
        else:
            result = run_isolated_scenario(scenario, deadline=deadline, budget=budget)
        from backend.task_evaluation.provenance import fingerprint, catalog_digest
        result = replace(result, metrics={**result.metrics, "dataset_hash": fingerprint(scenario.model_dump(mode="json")), "catalog_digest": catalog_digest()})
        records.append(to_run_record(result, mode=mode, git_sha=git_sha, config_fingerprint=config_fingerprint))
    return records
