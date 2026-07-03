from __future__ import annotations

import json

from backend.agent.graph import run_fitlife_agent
from backend.tools.data_access import data_path, read_eval_cases


def run_evaluation(limit: int | None = None) -> dict:
    cases = read_eval_cases()
    if limit is not None:
        cases = cases[:limit]

    results = []
    for case in cases:
        response = run_fitlife_agent(case.question)
        trace = response.get("trace", {})
        answer = response.get("answer_markdown", "")
        checks = _build_case_checks(case, trace, answer)
        check_results = {check["name"]: check["passed"] for check in checks}
        tool_ok = check_results["tool_call"]
        retrieval_ok = check_results["retrieval"]
        keywords_ok = check_results["keywords"]
        structured_ok = check_results["answer_format"]
        validator_ok = check_results["validator"]
        passed = all(check_results.values())
        results.append(
            {
                "question": case.question,
                "expected_tool": case.expected_tool,
                "expected_retrieval_doc": case.expected_retrieval_doc,
                "passed": passed,
                "tool_ok": tool_ok,
                "retrieval_ok": retrieval_ok,
                "structured_ok": structured_ok,
                "keywords_ok": keywords_ok,
                "validator_ok": validator_ok,
                "checks": checks,
                "failure_reasons": [check["reason"] for check in checks if not check["passed"]],
                "trace": trace,
            }
        )

    total = len(results)
    metric = lambda key: _rate([item[key] for item in results])
    output = {
        "total_tests": total,
        "pass_rate": _rate([item["passed"] for item in results]),
        "tool_call_success_rate": metric("tool_ok"),
        "retrieval_hit_rate": metric("retrieval_ok"),
        "structured_output_success_rate": metric("structured_ok"),
        "preference_compliance_rate": metric("keywords_ok"),
        "validator_pass_rate": metric("validator_ok"),
        "group_metrics": _group_metrics(results),
        "failed_cases": [item for item in results if not item["passed"]],
        "cases": results,
    }
    data_path("eval_results.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    data_path("eval_results.md").write_text(_format_markdown_summary(output), encoding="utf-8")
    return output


def _build_case_checks(case, trace: dict, answer: str) -> list[dict]:
    tool_calls = list(trace.get("tool_calls", []))
    retrieved_sources = list(trace.get("retrieved_sources", []))
    missing_keywords = [keyword for keyword in case.expected_keywords if keyword not in answer]

    tool_ok = not case.expected_tool or case.expected_tool in tool_calls
    retrieval_ok = not case.expected_retrieval_doc or case.expected_retrieval_doc in retrieved_sources
    keywords_ok = not missing_keywords
    structured_ok = "##" in answer if case.expected_answer_format == "markdown" else True
    validator_ok = bool(trace.get("validation_passed", True))

    return [
        _check(
            name="tool_call",
            passed=tool_ok,
            expected=case.expected_tool,
            observed=tool_calls,
            pass_reason="Expected tool was called." if case.expected_tool else "No specific tool expected.",
            fail_reason=f"Expected tool {case.expected_tool} but observed {tool_calls}.",
        ),
        _check(
            name="retrieval",
            passed=retrieval_ok,
            expected=case.expected_retrieval_doc,
            observed=retrieved_sources,
            pass_reason=(
                "Expected retrieval source was found."
                if case.expected_retrieval_doc
                else "No retrieval source expected."
            ),
            fail_reason=f"Expected retrieval source {case.expected_retrieval_doc} but observed {retrieved_sources}.",
        ),
        _check(
            name="keywords",
            passed=keywords_ok,
            expected=case.expected_keywords,
            observed=[keyword for keyword in case.expected_keywords if keyword in answer],
            pass_reason="All expected keywords were present.",
            fail_reason=f"Missing expected keywords: {', '.join(missing_keywords)}.",
        ),
        _check(
            name="answer_format",
            passed=structured_ok,
            expected=case.expected_answer_format,
            observed="markdown" if "##" in answer else "plain_text",
            pass_reason=f"Answer matched expected {case.expected_answer_format} format.",
            fail_reason=f"Expected {case.expected_answer_format} answer format but observed plain_text.",
        ),
        _check(
            name="validator",
            passed=validator_ok,
            expected=True,
            observed=validator_ok,
            pass_reason="Validator passed.",
            fail_reason="Validator reported failure.",
        ),
    ]


def _check(
    *,
    name: str,
    passed: bool,
    expected,
    observed,
    pass_reason: str,
    fail_reason: str,
) -> dict:
    return {
        "name": name,
        "passed": passed,
        "expected": expected,
        "observed": observed,
        "reason": pass_reason if passed else fail_reason,
    }


def _group_metrics(results: list[dict]) -> dict:
    return {
        "by_expected_tool": _group_by(results, lambda item: item["expected_tool"] or "none"),
        "by_retrieval_requirement": _group_by(
            results,
            lambda item: "requires_retrieval" if item["expected_retrieval_doc"] else "no_retrieval_expected",
        ),
    }


def _group_by(results: list[dict], key_fn) -> dict:
    grouped: dict[str, list[dict]] = {}
    for item in results:
        grouped.setdefault(key_fn(item), []).append(item)
    return {
        key: {
            "total": len(items),
            "pass_rate": _rate([item["passed"] for item in items]),
        }
        for key, items in sorted(grouped.items())
    }


def _format_markdown_summary(output: dict) -> str:
    lines = [
        "# FitLife Agent Evaluation",
        "",
        f"- Total tests: {output['total_tests']}",
        f"- Pass rate: {output['pass_rate']}",
        f"- Tool call success rate: {output['tool_call_success_rate']}",
        f"- Retrieval hit rate: {output['retrieval_hit_rate']}",
        f"- Structured output success rate: {output['structured_output_success_rate']}",
        f"- Preference compliance rate: {output['preference_compliance_rate']}",
        f"- Validator pass rate: {output['validator_pass_rate']}",
        "",
        "## Group Metrics",
        "",
    ]
    for group_name, metrics in output["group_metrics"].items():
        lines.append(f"### {group_name}")
        for key, value in metrics.items():
            lines.append(f"- {key}: {value['pass_rate']} ({value['total']} cases)")
        lines.append("")

    lines.extend(["## Failed Cases", ""])
    if not output["failed_cases"]:
        lines.append("- None")
    else:
        for item in output["failed_cases"]:
            lines.append(f"- {item['question']}")
            for reason in item["failure_reasons"]:
                lines.append(f"  - {reason}")
    lines.append("")
    return "\n".join(lines)


def _rate(values: list[bool]) -> float:
    if not values:
        return 0
    return round(sum(1 for value in values if value) / len(values), 4)
