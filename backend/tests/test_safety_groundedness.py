"""Groundedness: numbers the draft states but the data does not support.

The writer is asked to state a number only when a tool result provides it. These
tests hold the check to both of its failure directions, because a check that flags
a legitimate answer is worse than no check at all: it teaches a reader to ignore the
caveat, and it makes the assistant look unreliable about its own records.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.agent.workflow import FitLifeWorkflow
from backend.safety import gate
from backend.safety.groundedness import (
    check_groundedness,
    claim_numbers,
    supporting_values,
)

UNITS = ("千卡", "克", "分钟", "kcal", "g")


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------

def test_only_unit_bearing_numbers_are_treated_as_claims():
    """A list index or a heading is not a measurement."""
    claims = claim_numbers("分 3 部分：热量 2100 千卡，蛋白 98 克。", UNITS)

    assert [claim.value for claim in claims] == [2100.0, 98.0]
    assert [claim.unit for claim in claims] == ["千卡", "克"]


def test_thousands_separators_and_decimals_parse():
    claims = claim_numbers("摄入 2,100 千卡，体脂 18.5%。", UNITS)

    assert [claim.value for claim in claims] == [2100.0, 18.5]


def test_a_percent_is_captured_as_a_unit_of_its_own():
    claim = claim_numbers("达成 78%", UNITS)[0]

    assert claim.value == 78.0
    assert claim.unit == "%"


# --------------------------------------------------------------------------
# what counts as supported
# --------------------------------------------------------------------------

def test_supporting_values_include_what_the_data_implies():
    """A writer that adds two grounded figures is still grounded."""
    values = supporting_values({"a": {"x": 100.0, "y": 20.0}})

    assert 100.0 in values
    assert 20.0 in values
    assert 120.0 in values  # sum
    assert 80.0 in values  # difference
    assert 500.0 in values  # ratio as a percentage


def test_booleans_are_not_figures():
    values = supporting_values({"met": True, "count": 3})

    assert 1.0 not in values
    assert 3.0 in values


# --------------------------------------------------------------------------
# the two directions
# --------------------------------------------------------------------------

def test_no_data_means_every_stated_measurement_is_unsupported():
    """The case worth catching: a fabricated average looks like a measured one."""
    report = check_groundedness("你日均摄入 2200 千卡。", allowed=(), units=UNITS)

    assert report.grounded is False
    assert [claim.value for claim in report.unsupported] == [2200.0]


def test_a_supported_number_is_left_alone():
    report = check_groundedness("你日均摄入 2100 千卡。", allowed=(2100.0,), units=UNITS)

    assert report.grounded is True
    assert report.unsupported == ()


def test_a_number_the_data_does_not_contain_is_reported():
    report = check_groundedness("你日均摄入 2200 千卡。", allowed=(2100.0, 98.0), units=UNITS)

    assert [claim.value for claim in report.unsupported] == [2200.0]


def test_rounding_within_tolerance_is_not_a_fabrication():
    """A writer that rounds 2098.4 to 2098 is reporting, not inventing."""
    assert check_groundedness("摄入 2098 千卡。", allowed=(2098.4,), units=UNITS).grounded
    assert check_groundedness("摄入 2100 千卡。", allowed=(2098.4,), units=UNITS).grounded
    # But a materially different figure still fails.
    assert not check_groundedness("摄入 2300 千卡。", allowed=(2098.4,), units=UNITS).grounded


def test_a_share_of_a_target_is_supported():
    """98g against a 126g target is 78%; reporting that is not an invention."""
    values = supporting_values({"weekly_average_protein": 98.0, "daily_protein_target": 126.0})

    report = check_groundedness("蛋白达成 78%。", allowed=values, units=UNITS)

    assert report.grounded is True


def test_an_answer_without_measurements_is_never_flagged():
    report = check_groundedness(
        "记录里这几天数据不足，可以先补充饮食记录。", allowed=(), units=UNITS
    )

    assert report.grounded is True
    assert report.claims == ()


# --------------------------------------------------------------------------
# through the gate
# --------------------------------------------------------------------------

def test_the_gate_appends_a_caveat_and_keeps_the_answer():
    result = gate.review_output(
        "我这周热量多少",
        "你日均摄入 2200 千卡，继续保持。",
        supporting_values=(2100.0,),
    )

    assert result.verdict.action == "disclose"
    assert "2200 千卡" in result.text  # the answer survives
    assert "未在本次读取" in result.text  # and says what to distrust


def test_the_gate_leaves_a_grounded_answer_untouched():
    result = gate.review_output(
        "我这周热量多少",
        "你日均摄入 2100 千卡。",
        supporting_values=(2100.0,),
    )

    assert result.verdict.action == "allow"
    assert result.text == "你日均摄入 2100 千卡。"


def test_omitting_the_data_leaves_the_check_off():
    """A caller with nothing to compare against must opt in, not get a free pass."""
    result = gate.review_output("我这周热量多少", "你日均摄入 2200 千卡。")

    assert result.verdict.action == "allow"
    assert result.text == "你日均摄入 2200 千卡。"


# --------------------------------------------------------------------------
# wiring
# --------------------------------------------------------------------------

class _Gateway:
    provider = "test"
    model = "test-model"

    def write_answer(self, state):
        return "x"


class _Context:
    def record(self, *args, **kwargs):
        pass


def _review(draft: str, tool_results: dict) -> str:
    workflow = FitLifeWorkflow(repository=None, gateway=_Gateway())
    state = {"user_query": "我这周热量多少", "final_answer": draft, "tool_results": tool_results}
    return asyncio.run(workflow._review(_Context(), state))["final_answer"]


@pytest.mark.parametrize("draft,tool_results,expected_caveat", [
    ("你日均 2100 千卡。", {"m": {"weekly_average_calories": 2100.0}}, False),
    ("你日均 2200 千卡。", {"m": {"weekly_average_calories": 2100.0}}, True),
    ("你日均 2200 千卡。", {}, True),
    ("你记录了 3 天。", {"m": {"weekly_average_calories": 0}}, False),
])
def test_the_review_step_compares_the_answer_against_its_own_data(
    draft, tool_results, expected_caveat
):
    answer = _review(draft, tool_results)

    assert ("未在本次读取" in answer) is expected_caveat
