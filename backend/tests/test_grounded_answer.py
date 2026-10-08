"""Rendering: what the model may say, and what the code says for it.

The load-bearing property is that a model cannot attach a number to a meaning the
catalog does not support. It names an id; the renderer writes the sentence. Text blocks
that do carry numbers are dropped, which is blunt on purpose and is the part of this
design most likely to lose a useful sentence - the tests record that rather than hide it.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.agent.grounded_answer import (
    NO_EVIDENCE_TEXT,
    PARTIAL_TEXT,
    AnswerBlock,
    GroundedAnswer,
    render_grounded_answer,
)
from backend.safety.evidence import EvidenceFact


def _fact(evidence_id="p1", metric="protein_intake", value="70", unit="g", scope="2026-10-07"):
    return EvidenceFact(evidence_id, metric, Decimal(value), unit, scope, f"path.{evidence_id}")


def _answer(*blocks) -> GroundedAnswer:
    return GroundedAnswer.model_validate({"blocks": list(blocks)})


# --------------------------------------------------------------------------
# the model cannot relabel a number
# --------------------------------------------------------------------------

def test_model_cannot_relabel_a_number():
    """The example from the plan: a protein fact must not come back as body weight."""
    evidence = {"p1": _fact()}
    answer = _answer({"kind": "fact", "evidence_id": "p1"})

    result = render_grounded_answer(answer, evidence)

    assert "2026-10-07" in result.text
    assert "蛋白质" in result.text
    assert "70" in result.text
    assert "体重" not in result.text


def test_a_fact_must_not_carry_its_own_value():
    """A fact states an id. If it could state a value, the catalog would be bypassed."""
    with pytest.raises(ValidationError):
        AnswerBlock.model_validate(
            {"kind": "fact", "evidence_id": "p1", "text": "蛋白质 999 g"}
        )


def test_a_fact_must_name_an_evidence_id():
    with pytest.raises(ValidationError):
        AnswerBlock.model_validate({"kind": "fact"})


def test_an_unknown_evidence_id_is_not_rendered():
    answer = _answer({"kind": "fact", "evidence_id": "not-in-the-catalog"})

    result = render_grounded_answer(answer, {"p1": _fact()})

    assert result.text == NO_EVIDENCE_TEXT
    assert result.reasons == ("unknown_evidence",)
    assert "not-in-the-catalog" not in result.text


def test_a_metric_without_a_label_is_not_rendered():
    """The model does not get to name a metric, and neither does a missing entry."""
    evidence = {"x1": _fact("x1", metric="mystery_metric")}
    answer = _answer({"kind": "fact", "evidence_id": "x1"})

    result = render_grounded_answer(answer, evidence)

    assert "mystery_metric" not in result.text
    assert result.reasons == ("invalid_block",)


# --------------------------------------------------------------------------
# the scope travels with the value
# --------------------------------------------------------------------------

def test_the_day_is_stated_with_the_value():
    """A figure without its day is how one day becomes another."""
    evidence = {"p1": _fact(scope="2026-10-07")}

    result = render_grounded_answer(_answer({"kind": "fact", "evidence_id": "p1"}), evidence)

    assert "2026-10-07" in result.text


def test_an_integral_value_is_rendered_without_a_decimal_point():
    evidence = {"p1": _fact(value="75")}

    result = render_grounded_answer(_answer({"kind": "fact", "evidence_id": "p1"}), evidence)

    assert "75 g" in result.text
    assert "75.0" not in result.text


# --------------------------------------------------------------------------
# text blocks
# --------------------------------------------------------------------------

def test_plain_text_is_kept():
    answer = _answer({"kind": "explanation", "text": "记录覆盖的训练类型比较均衡。"})

    result = render_grounded_answer(answer, {"p1": _fact()})

    assert "记录覆盖的训练类型比较均衡。" in result.text
    assert result.invalid_blocks == 0


@pytest.mark.parametrize("text", [
    "建议每天补充 70g 蛋白质。",
    "你的达成率是 78%。",
    "每周训练三次。",
    "摄入约一千卡。",
    "目标是 1800 kcal。",
])
def test_a_text_block_carrying_a_number_is_dropped(text):
    """This check can see a numeral; it cannot see whether the numeral is right."""
    answer = _answer({"kind": "explanation", "text": text})

    result = render_grounded_answer(answer, {"p1": _fact()})

    assert text not in result.text
    assert result.reasons == ("unbound_numeric_text",)


def test_a_recommendation_cannot_use_its_label_to_smuggle_a_number():
    answer = _answer({"kind": "recommendation", "text": "建议每天补充 70g 蛋白质。"})

    result = render_grounded_answer(answer, {"p1": _fact()})

    assert "70" not in result.text
    assert result.reasons == ("unbound_numeric_text",)


def test_a_plain_recommendation_is_kept_and_labelled():
    answer = _answer({"kind": "recommendation", "text": "可以适当增加训练频率。"})

    result = render_grounded_answer(answer, {"p1": _fact()})

    assert "建议：" in result.text
    assert "可以适当增加训练频率。" in result.text


def test_a_text_block_must_not_name_an_evidence_id():
    with pytest.raises(ValidationError):
        AnswerBlock.model_validate(
            {"kind": "explanation", "text": "说明", "evidence_id": "p1"}
        )


# --------------------------------------------------------------------------
# partial answers and the empty catalog
# --------------------------------------------------------------------------

def test_a_valid_fact_survives_a_neighbouring_invalid_one():
    answer = _answer(
        {"kind": "fact", "evidence_id": "p1"},
        {"kind": "fact", "evidence_id": "missing"},
    )

    result = render_grounded_answer(answer, {"p1": _fact()})

    assert "70" in result.text
    assert result.invalid_blocks == 1
    assert PARTIAL_TEXT in result.text


def test_an_empty_catalog_states_the_limitation_instead_of_guessing():
    answer = _answer({"kind": "explanation", "text": "看起来不错。"})

    result = render_grounded_answer(answer, {})

    assert result.text == NO_EVIDENCE_TEXT
    assert result.reasons == ("no_evidence",)
    assert "看起来不错" not in result.text


def test_when_every_block_is_invalid_a_controlled_message_is_returned():
    answer = _answer({"kind": "fact", "evidence_id": "missing"})

    result = render_grounded_answer(answer, {"p1": _fact()})

    assert result.text == NO_EVIDENCE_TEXT


def test_the_original_model_text_is_never_returned_wholesale():
    """Falling back to the raw answer would discard the point of the renderer."""
    answer = _answer({"kind": "explanation", "text": "消耗了 900 千卡。"})

    result = render_grounded_answer(answer, {})

    assert "900" not in result.text


def test_the_extra_field_is_bounded():
    with pytest.raises(ValidationError):
        AnswerBlock.model_validate({"kind": "explanation", "text": "x", "unexpected": 1})


def test_the_block_count_is_bounded():
    blocks = [{"kind": "explanation", "text": "说明"} for _ in range(21)]

    with pytest.raises(ValidationError):
        GroundedAnswer.model_validate({"blocks": blocks})
