from backend.schemas import TargetProgress, TodayOverview, UserProfile
from backend.tools.calendar_store import get_daily_detail
from backend.tools.data_access import read_profile


def build_today_overview(day: str, user_id: str | None = None) -> TodayOverview:
    profile = read_profile(user_id)
    detail = get_daily_detail(day, user_id)
    summary = detail.summary
    return TodayOverview(
        date=day,
        summary=summary,
        meals=detail.meals,
        workouts=detail.workouts,
        targets=[
            _progress("Calories", summary.calories, profile.daily_calorie_target, "kcal"),
            _progress("Protein", summary.protein, profile.daily_protein_target, "g"),
            _progress("Training", summary.training_sessions, 1 if profile.weekly_training_frequency else 0, "sessions"),
        ],
        coach_actions=_coach_actions(profile, summary.training_sessions),
    )


def _progress(label: str, current: float, target: float, unit: str) -> TargetProgress:
    remaining = target - current
    status = "met" if remaining <= 0 else "under"
    if label == "Calories" and current > target * 1.1:
        status = "over"
    return TargetProgress(label=label, current=current, target=target, unit=unit, remaining=remaining, status=status)


def _coach_actions(profile: UserProfile, training_sessions: int) -> list[str]:
    actions = ["explain_today", "suggest_next_meal"]
    if training_sessions == 0 and profile.weekly_training_frequency > 0:
        actions.append("adjust_today_training")
    return actions
