"""Facts a grounded answer may cite, built only from whitelisted tool output.

The earlier check compared the draft's numbers against every number in the tool
results, so a weight of 70 also "supported" a protein of 70g and two different days
were interchangeable. A bare number is not evidence. Evidence has a metric, a unit and
a scope, and the scope is what stops a figure from one day, or one metric, being
presented as another.

Nothing here accepts an evidence value from a model, a user or a document: the catalog
is derived from tool results by this module alone. A model that could assert its own
evidence would make the whole check decorative.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# Bounded so the catalog cannot become the quadratic set the old heuristic was, and so
# the writer payload stays a size the model can actually use.
MAX_EVIDENCE = 512


class EvidenceLimitExceeded(ValueError):
    """More facts than the catalog will hold.

    Raised rather than truncated: silently dropping facts and then claiming the answer
    was checked would be worse than failing.
    """


@dataclass(frozen=True)
class EvidenceFact:
    id: str
    metric: str
    value: Decimal
    unit: str
    scope: str
    source_path: str


# metric -> (unit, whether a negative is meaningful). Intake, duration and counts
# cannot be negative; a negative here means the source is broken, not that the user
# did something unusual.
_METRICS: dict[str, tuple[str, bool]] = {
    "energy_intake": ("kcal", False),
    "protein_intake": ("g", False),
    "carbohydrate_intake": ("g", False),
    "fat_intake": ("g", False),
    "recorded_day_mean_energy": ("kcal", False),
    "recorded_day_mean_protein": ("g", False),
    "training_record_count": ("条", False),
    "training_duration": ("min", False),
    "strength_volume": ("kg·次", False),
}

_DAILY_FIELDS: tuple[tuple[str, str], ...] = (
    ("calories", "energy_intake"),
    ("protein", "protein_intake"),
    ("carbs", "carbohydrate_intake"),
    ("fat", "fat_intake"),
)


def _decimal(value) -> Decimal | None:
    """A usable figure, or None if the source is not one.

    bool is rejected explicitly: it is an int in Python, and `True` would otherwise
    become the number 1 in an answer about the user's intake.
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return number


def _fact(metric: str, value, scope: str, source_path: str) -> EvidenceFact | None:
    number = _decimal(value)
    if number is None:
        return None
    unit, allows_negative = _METRICS[metric]
    if not allows_negative and number < 0:
        return None
    # The id is derived from where the fact came from, so the same source cannot
    # produce two ids and two sources cannot collide.
    return EvidenceFact(
        id=f"{metric}:{scope}" if scope else metric,
        metric=metric,
        value=number,
        unit=unit,
        scope=scope,
        source_path=source_path,
    )


def _recorded_days(daily_totals: dict) -> list[str]:
    return sorted(str(day) for day in daily_totals)


def build_evidence(tool_results) -> dict[str, EvidenceFact]:
    """The facts this run's tool results support, keyed by id.

    Only the whitelisted fields below are read. Anything else in the tool results is
    ignored rather than swept in.
    """
    if not isinstance(tool_results, dict):
        return {}

    facts: list[EvidenceFact] = []
    meal = tool_results.get("meal_analysis")
    if isinstance(meal, dict):
        daily = meal.get("daily_totals")
        if isinstance(daily, dict):
            for day, totals in daily.items():
                if not isinstance(totals, dict):
                    continue
                for field, metric in _DAILY_FIELDS:
                    fact = _fact(
                        metric, totals.get(field), str(day),
                        f"meal_analysis.daily_totals.{day}.{field}",
                    )
                    if fact is not None:
                        facts.append(fact)

        # The average covers the days that have records. Naming it after those days
        # keeps it from being read as an average over a whole calendar week, which the
        # analyser does not compute and does not fill with zeros.
        #
        # An empty set produces no average fact at all. The analyser reports 0 for it,
        # and 0 here would be an assertion about the user - "your intake was zero" -
        # when the truth is that nothing was recorded.
        days = _recorded_days(daily) if isinstance(daily, dict) else []
        if days:
            scope = "、".join(days)
            for field, metric in (
                ("weekly_average_calories", "recorded_day_mean_energy"),
                ("weekly_average_protein", "recorded_day_mean_protein"),
            ):
                fact = _fact(metric, meal.get(field), scope, f"meal_analysis.{field}")
                if fact is not None:
                    facts.append(fact)

    workout = tool_results.get("workout_analysis")
    if isinstance(workout, dict):
        counts = workout.get("weekly_training_counts")
        if isinstance(counts, dict):
            for week, count in counts.items():
                fact = _fact(
                    "training_record_count", count, str(week),
                    f"workout_analysis.weekly_training_counts.{week}",
                )
                if fact is not None:
                    facts.append(fact)
        durations = workout.get("weekly_duration_min")
        if isinstance(durations, dict):
            for week, minutes in durations.items():
                fact = _fact(
                    "training_duration", minutes, str(week),
                    f"workout_analysis.weekly_duration_min.{week}",
                )
                if fact is not None:
                    facts.append(fact)
        weeks = "、".join(sorted(str(week) for week in counts)) if isinstance(counts, dict) else ""
        fact = _fact(
            "strength_volume", workout.get("total_strength_volume"), weeks,
            "workout_analysis.total_strength_volume",
        )
        if fact is not None:
            facts.append(fact)

    catalog: dict[str, EvidenceFact] = {}
    for fact in facts:
        if len(catalog) >= MAX_EVIDENCE:
            raise EvidenceLimitExceeded(
                f"More than {MAX_EVIDENCE} evidence facts were produced"
            )
        catalog[fact.id] = fact
    return catalog
