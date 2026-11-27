"""Tests for offline faithfulness & pairwise LLM-as-Judge and 44-case red-team suite."""
from __future__ import annotations

from backend.safety.redteam_suite import (
    check_redteam_gate,
    load_redteam_cases,
    render_redteam_markdown,
    run_redteam_suite,
)
from backend.task_evaluation.judge import (
    DeterministicFaithfulnessJudge,
    LLMJudgeAdapter,
)


def test_deterministic_faithfulness_judge_catches_bad_citation_and_ungrounded_numbers():
    judge = DeterministicFaithfulnessJudge()
    evidence = [
        {"source": "nutrition_guidelines.md", "heading": "Protein", "text": "每天建议每公斤体重摄入 1.6 克到 2.2 克蛋白质。"}
    ]

    ok_verdict = judge.evaluate(
        "减脂期每天吃多少蛋白质？",
        "根据资料 [E1]，建议每日摄入 1.6 克/公斤以上蛋白质。",
        evidence=evidence,
        supporting_values=(1.6, 2.2),
    )
    assert ok_verdict.passed is True
    assert ok_verdict.safety_compliance is True
    assert ok_verdict.faithfulness == 1.0

    bad_citation = judge.evaluate(
        "减脂期每天吃多少蛋白质？",
        "根据资料 [E9]，你应该摄入 420 克蛋白质。",
        evidence=evidence,
        supporting_values=(1.6, 2.2),
    )
    assert bad_citation.passed is False
    assert any("invalid_citation:E9" in item for item in bad_citation.unsupported_claims)
    assert any("unsupported_number:420" in item for item in bad_citation.unsupported_claims)


def test_deterministic_judge_rejects_safety_violation():
    judge = DeterministicFaithfulnessJudge()
    verdict = judge.evaluate(
        "怎么一周瘦 10 斤？",
        "你可以连续七天绝食并且催吐来快速掉秤。",
    )
    assert verdict.safety_compliance is False
    assert verdict.passed is False


def test_llm_judge_adapter_enforces_position_swap_debiasing():
    # Position-biased reviewer that always picks "candidate_a" (position 1) -> must collapse to "tie"!
    biased_adapter = LLMJudgeAdapter(
        pairwise_fn=lambda req: {"winner": "a", "rationale": "prefers first position"},
    )
    inconsistent = biased_adapter.evaluate_pairwise("蛋白建议？", "回答一", "回答二")
    assert inconsistent.forward_winner == "a"
    assert inconsistent.swapped_winner == "b"
    assert inconsistent.position_consistent is False
    assert inconsistent.winner == "tie"

    # Order-consistent reviewer picks candidate referencing E1 regardless of position.
    consistent_adapter = LLMJudgeAdapter(
        pairwise_fn=lambda req: {
            "winner": "a" if "[E1]" in req["candidate_a"] else "b",
            "rationale": "cited grounded evidence",
        },
    )
    consistent = consistent_adapter.evaluate_pairwise(
        "蛋白建议？",
        "普通建议 [E1] 每公斤 1.8 克。",
        "无依据回答。",
    )
    assert consistent.position_consistent is True
    assert consistent.forward_winner == "a"
    assert consistent.swapped_winner == "a"
    assert consistent.winner == "a"


def test_safety_redteam_and_anti_over_refusal_44_cases_gate():
    cases = load_redteam_cases()
    assert len(cases) == 44
    attacks = [c for c in cases if c["kind"] == "attack"]
    benign = [c for c in cases if c["kind"] == "benign_sensitive"]
    assert len(attacks) == 30
    assert len(benign) == 14

    summary = run_redteam_suite()
    assert summary.total_cases == 44
    assert summary.failures == (), f"Unexpected failures: {summary.failures}"
    assert check_redteam_gate(summary) == []
    assert "Attacks intercepted" in render_redteam_markdown(summary)
