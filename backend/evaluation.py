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
        trace = response["trace"]
        answer = response["answer_markdown"]
        tool_ok = not case.expected_tool or case.expected_tool in trace.get("tool_calls", [])
        retrieval_ok = not case.expected_retrieval_doc or case.expected_retrieval_doc in trace.get("retrieved_sources", [])
        keywords_ok = all(keyword in answer for keyword in case.expected_keywords)
        structured_ok = "##" in answer if case.expected_answer_format == "markdown" else True
        validator_ok = bool(trace.get("validation_passed", True))
        passed = all([tool_ok, retrieval_ok, keywords_ok, structured_ok, validator_ok])
        results.append(
            {
                "question": case.question,
                "passed": passed,
                "tool_ok": tool_ok,
                "retrieval_ok": retrieval_ok,
                "structured_ok": structured_ok,
                "keywords_ok": keywords_ok,
                "validator_ok": validator_ok,
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
        "failed_cases": [item for item in results if not item["passed"]],
        "cases": results,
    }
    data_path("eval_results.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def _rate(values: list[bool]) -> float:
    if not values:
        return 0
    return round(sum(1 for value in values if value) / len(values), 4)
