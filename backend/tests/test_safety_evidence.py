"""The evidence catalog: what a fact is, and what disqualifies a number from being one.

The property under test throughout is that a figure cannot change meaning. A weight is
not a protein intake, one day is not another, and a missing record is not zero. The
previous check could not tell those apart because it compared bare numbers.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from backend.safety.evidence import (
    MAX_EVIDENCE,
    EvidenceLimitExceeded,
    build_evidence,
)

DAILY = {
    "meal_analysis": {
        "daily_totals": {"2026-10-07": {"calories": 1800, "protein": 70}},
        "weekly_average_calories": 1800,
        "weekly_average_protein": 70,
    }
}


def _metrics(catalog):
    return sorted(fact.metric for fact in catalog.values())


# --------------------------------------------------------------------------
# the two things a bare number could not distinguish
# --------------------------------------------------------------------------

def test_two_metrics_on_the_same_day_are_different_facts():
    catalog = build_evidence(DAILY)

    assert "energy_intake" in _metrics(catalog)
    assert "protein_intake" in _metrics(catalog)
    energy = next(f for f in catalog.values() if f.metric == "energy_intake")
    protein = next(f for f in catalog.values() if f.metric == "protein_intake")
    assert energy.unit == "kcal"
    assert protein.unit == "g"


def test_the_same_metric_on_two_days_are_different_facts():
    catalog = build_evidence({
        "meal_analysis": {
            "daily_totals": {
                "2026-10-07": {"protein": 70},
                "2026-10-08": {"protein": 70},
            }
        }
    })

    scopes = sorted(fact.scope for fact in catalog.values() if fact.metric == "protein_intake")
    assert scopes == ["2026-10-07", "2026-10-08"]
    # Same value, different day, different fact: the id cannot collide.
    assert len(catalog) == 2


def test_a_body_weight_is_not_intake_evidence():
    """The old check let a weight of 70 support a protein of 70g."""
    catalog = build_evidence({**DAILY, "profile": {"weight_kg": 70}})

    assert all("weight" not in fact.source_path for fact in catalog.values())
    assert _metrics(catalog) == [
        "energy_intake", "protein_intake", "recorded_day_mean_energy",
        "recorded_day_mean_protein",
    ]


# --------------------------------------------------------------------------
# what is not a fact
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_number_is_not_evidence(value):
    catalog = build_evidence({
        "meal_analysis": {"daily_totals": {"2026-10-07": {"calories": value}}}
    })

    assert catalog == {}


def test_a_boolean_is_not_evidence():
    """`True` is 1 in Python and would read as an intake of one."""
    catalog = build_evidence({
        "meal_analysis": {
            "daily_totals": {"2026-10-07": {"calories": True, "protein": False}}
        }
    })

    assert catalog == {}


@pytest.mark.parametrize("value", [-1, -1800, -0.5])
def test_a_negative_intake_is_not_evidence(value):
    catalog = build_evidence({
        "meal_analysis": {"daily_totals": {"2026-10-07": {"calories": value}}}
    })

    assert catalog == {}


def test_a_negative_training_duration_is_not_evidence():
    catalog = build_evidence({"workout_analysis": {"weekly_duration_min": {"2026-W41": -30}}})

    assert catalog == {}


def test_an_unparseable_value_is_not_evidence():
    catalog = build_evidence({
        "meal_analysis": {"daily_totals": {"2026-10-07": {"calories": "not a number"}}}
    })

    assert catalog == {}


def test_unknown_fields_are_ignored_rather_than_swept_in():
    catalog = build_evidence({
        "meal_analysis": {"daily_totals": {"2026-10-07": {"mystery": 42, "calories": 1800}}},
        "something_else": {"count": 7},
    })

    assert _metrics(catalog) == ["energy_intake"]


def test_an_empty_record_set_produces_no_intake_facts():
    """A missing record is not an intake of zero."""
    catalog = build_evidence({
        "meal_analysis": {
            "daily_totals": {},
            "weekly_average_calories": 0,
            "weekly_average_protein": 0,
            "highest_calorie_food": None,
        }
    })

    # The analyser reports 0 for an empty set. That is not a measurement of the user,
    # so nothing is produced at all - not even the averages.
    assert catalog == {}


# --------------------------------------------------------------------------
# scope wording
# --------------------------------------------------------------------------

def test_the_average_is_scoped_to_the_days_that_have_records():
    """It must not read as an average over a whole calendar week."""
    catalog = build_evidence({
        "meal_analysis": {
            "daily_totals": {"2026-10-07": {"protein": 70}, "2026-10-08": {"protein": 80}},
            "weekly_average_protein": 75,
        }
    })

    mean = next(f for f in catalog.values() if f.metric == "recorded_day_mean_protein")
    assert mean.scope == "2026-10-07、2026-10-08"
    assert mean.value == Decimal("75")


def test_training_counts_are_scoped_to_their_week():
    catalog = build_evidence({
        "workout_analysis": {
            "weekly_training_counts": {"2026-W41": 2},
            "weekly_duration_min": {"2026-W41": 75.5},
            "total_strength_volume": 1800,
        }
    })

    count = next(f for f in catalog.values() if f.metric == "training_record_count")
    assert count.scope == "2026-W41"
    assert count.unit == "条"
    volume = next(f for f in catalog.values() if f.metric == "strength_volume")
    assert volume.unit == "kg·次"


# --------------------------------------------------------------------------
# bounds
# --------------------------------------------------------------------------

def test_the_catalog_is_bounded_and_says_so_instead_of_truncating():
    # 12 months x 31 days = 372 records x 4 intake fields, comfortably past the bound.
    days = {f"2026-{month:02d}-{day:02d}": {"calories": 100, "protein": 10, "carbs": 5, "fat": 2}
            for month in range(1, 13) for day in range(1, 32)}
    assert len(days) * 4 > MAX_EVIDENCE

    with pytest.raises(EvidenceLimitExceeded):
        build_evidence({"meal_analysis": {"daily_totals": days}})


def test_a_catalog_within_the_bound_is_returned_whole():
    days = {f"2026-10-{day:02d}": {"calories": 100} for day in range(1, 11)}
    catalog = build_evidence({"meal_analysis": {"daily_totals": days}})

    assert len(catalog) == 10


def test_a_non_mapping_tool_result_is_not_evidence():
    assert build_evidence(None) == {}
    assert build_evidence("nope") == {}
