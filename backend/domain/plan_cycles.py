"""Periodized plan cycle domain models, catalog-backed builder, validation, and adherence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from backend.domain.exercise_progress import ExerciseProgressSummary
from backend.domain.training_context import TrainingContext

GoalType = Literal["fat_loss", "muscle_gain", "maintenance", "recomposition", "custom"]
CycleStatus = Literal["draft", "active", "completed", "archived"]
CycleSource = Literal["manual", "deterministic", "agent", "weekly_auto", "weekly_auto_deterministic"]
DayType = Literal["training", "rest", "cardio"]
AdherenceStatus = Literal["completed", "missed", "upcoming", "rest", "skipped"]


@dataclass(frozen=True)
class PrescribedExercise:
    catalog_exercise_id: str | None
    name: str
    primary_muscle: str
    exercise_type: Literal["strength", "cardio"] = "strength"
    sets: int = 3
    reps: int = 10
    target_weight_kg: float | None = None
    duration_min: int | None = None
    rest_sec: int = 90
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "catalog_exercise_id": self.catalog_exercise_id,
            "name": self.name,
            "primary_muscle": self.primary_muscle,
            "exercise_type": self.exercise_type,
            "sets": self.sets,
            "reps": self.reps,
            "target_weight_kg": self.target_weight_kg,
            "duration_min": self.duration_min,
            "rest_sec": self.rest_sec,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "PrescribedExercise":
        ex_type = "cardio" if raw.get("exercise_type") == "cardio" else "strength"
        return cls(
            catalog_exercise_id=str(raw["catalog_exercise_id"]) if raw.get("catalog_exercise_id") else None,
            name=str(raw.get("name", "")),
            primary_muscle=str(raw.get("primary_muscle", "full_body")),
            exercise_type=ex_type,
            sets=max(1, min(12, int(raw.get("sets") or 3))),
            reps=max(1, min(60, int(raw.get("reps") or 10))),
            target_weight_kg=float(raw["target_weight_kg"]) if raw.get("target_weight_kg") is not None else None,
            duration_min=int(raw["duration_min"]) if raw.get("duration_min") is not None else None,
            rest_sec=max(15, min(300, int(raw.get("rest_sec") or 90))),
            notes=str(raw.get("notes") or ""),
        )


@dataclass(frozen=True)
class CyclePhase:
    name: str
    start_week: int
    end_week: int
    focus: str
    volume_multiplier: float = 1.0

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "start_week": self.start_week,
            "end_week": self.end_week,
            "focus": self.focus,
            "volume_multiplier": self.volume_multiplier,
        }


@dataclass(frozen=True)
class PlanDay:
    id: str
    cycle_id: str
    user_id: str
    week_index: int
    day_of_week: int
    scheduled_date: str
    day_type: DayType
    focus: str
    estimated_duration_min: int | None
    prescribed_exercises: tuple[PrescribedExercise, ...]
    nutrition_override: dict[str, object]
    status_override: Literal["skipped"] | None = None
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self, *, adherence: AdherenceStatus | None = None, logged_session_count: int = 0) -> dict[str, object]:
        data: dict[str, object] = {
            "id": self.id,
            "cycle_id": self.cycle_id,
            "week_index": self.week_index,
            "day_of_week": self.day_of_week,
            "scheduled_date": self.scheduled_date,
            "day_type": self.day_type,
            "focus": self.focus,
            "estimated_duration_min": self.estimated_duration_min,
            "prescribed_exercises": [ex.to_dict() for ex in self.prescribed_exercises],
            "nutrition_override": dict(self.nutrition_override),
            "status_override": self.status_override,
            "notes": self.notes,
        }
        if adherence is not None:
            data["adherence"] = adherence
            data["logged_session_count"] = logged_session_count
        return data


@dataclass(frozen=True)
class PlanCycle:
    id: str
    user_id: str
    title: str
    goal_type: GoalType
    start_date: str
    duration_weeks: int
    phases: tuple[CyclePhase, ...]
    status: CycleStatus
    source: CycleSource
    rationale: dict[str, object]
    version: int
    created_at: str
    updated_at: str
    activated_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "goal_type": self.goal_type,
            "start_date": self.start_date,
            "duration_weeks": self.duration_weeks,
            "phases": [phase.to_dict() for phase in self.phases],
            "status": self.status,
            "source": self.source,
            "rationale": dict(self.rationale),
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "activated_at": self.activated_at,
        }


@dataclass(frozen=True)
class CatalogExerciseOption:
    id: str
    name: str
    exercise_type: Literal["strength", "cardio"]
    primary_muscle: str
    equipment: str
    mechanic: str
    level: str


EQUIPMENT_TO_CATALOG: dict[str, tuple[str, ...]] = {
    "barbell": ("barbell", "e-z curl bar"),
    "dumbbell": ("dumbbell",),
    "machine": ("machine",),
    "cable": ("cable",),
    "bodyweight": ("body only", "none", ""),
    "kettlebell": ("kettlebells",),
    "resistance_band": ("bands",),
    "cardio_machine": ("machine", "other", "body only"),
}

INJURY_AVOID_MUSCLES: dict[str, tuple[str, ...]] = {
    "knee": ("股四头肌", "quadriceps"),
    "lower_back": ("下背部肌群", "lower back"),
    "shoulder": ("肩部肌群", "shoulders"),
}

PUSH_MUSCLES = ("胸肌", "肩部肌群", "肱三头肌", "chest", "shoulders", "triceps")
PULL_MUSCLES = ("背阔肌", "中背部肌群", "肱二头肌", "斜方肌", "lats", "middle back", "biceps")
LEG_MUSCLES = ("股四头肌", "腘绳肌", "臀肌", "小腿肌群", "quadriceps", "hamstrings", "glutes", "calves")
CORE_MUSCLES = ("腹肌", "abdominals", "core")


def monday_of_week(anchor: date) -> date:
    return anchor - timedelta(days=anchor.weekday())


def build_cycle_phases(duration_weeks: int, goal_type: GoalType) -> tuple[CyclePhase, ...]:
    if duration_weeks <= 2:
        return (CyclePhase(name="核心推进期", start_week=1, end_week=duration_weeks, focus=goal_type, volume_multiplier=1.0),)
    if duration_weeks <= 4:
        return (
            CyclePhase(name="适应与建立期", start_week=1, end_week=1, focus="technique_base", volume_multiplier=0.85),
            CyclePhase(name="负荷推进期", start_week=2, end_week=duration_weeks, focus=goal_type, volume_multiplier=1.0),
        )
    deload_week = max(duration_weeks - 1, 2)
    return (
        CyclePhase(name="适应与动作建立", start_week=1, end_week=2, focus="technique_base", volume_multiplier=0.85),
        CyclePhase(name="渐进负荷推进", start_week=3, end_week=deload_week - 1, focus=goal_type, volume_multiplier=1.05),
        CyclePhase(name="减载恢复周", start_week=deload_week, end_week=deload_week, focus="deload_recovery", volume_multiplier=0.75),
        CyclePhase(name="巩固与测试周", start_week=duration_weeks, end_week=duration_weeks, focus="consolidation", volume_multiplier=1.0),
    )


def choose_split(ctx: TrainingContext) -> str:
    if ctx.preferred_split != "auto":
        return ctx.preferred_split
    days = min(ctx.weekly_available_days, 6)
    if days <= 3:
        return "full_body"
    if days == 4:
        return "upper_lower"
    return "push_pull_legs"


def _schedule_day_slots(training_days: int, split: str, goal_type: GoalType) -> list[tuple[DayType, str, tuple[str, ...]]]:
    """Return 7 entries (Mon..Sun) with at least 1 mandatory rest day."""
    safe_days = max(1, min(training_days, 6))
    slots: list[tuple[DayType, str, tuple[str, ...]]] = [("rest", "恢复休息日", ()) for _ in range(7)]

    if split == "push_pull_legs" and safe_days >= 5:
        patterns: list[tuple[DayType, str, tuple[str, ...]]] = [
            ("training", "推类力量（胸/肩/三头）", PUSH_MUSCLES),
            ("training", "拉类力量（背/二头）", PULL_MUSCLES),
            ("training", "下肢力量（腿/臀）", LEG_MUSCLES),
            ("training", "推类与核心", PUSH_MUSCLES + CORE_MUSCLES),
            ("training", "拉类与下肢辅助", PULL_MUSCLES + LEG_MUSCLES),
            ("cardio", "低强度有氧与核心" if goal_type == "fat_loss" else "下肢与体能", LEG_MUSCLES + CORE_MUSCLES),
        ]
        day_indices = [0, 1, 2, 4, 5, 6][:safe_days]
    elif split == "upper_lower" and safe_days >= 4:
        patterns = [
            ("training", "上肢力量 A（推拉平衡）", PUSH_MUSCLES + PULL_MUSCLES),
            ("training", "下肢力量 A（腿/臀/核心）", LEG_MUSCLES + CORE_MUSCLES),
            ("training", "上肢力量 B（肩背与手臂）", PULL_MUSCLES + PUSH_MUSCLES),
            ("training", "下肢力量 B（后链与核心）", LEG_MUSCLES + CORE_MUSCLES),
            ("cardio", "有氧与主动恢复", CORE_MUSCLES),
            ("training", "全身补强", PUSH_MUSCLES + PULL_MUSCLES + LEG_MUSCLES),
        ]
        day_indices = [0, 1, 3, 4, 5, 6][:safe_days]
    else:
        patterns = [
            ("training", "全身力量 A（下肢+推）", LEG_MUSCLES + PUSH_MUSCLES),
            ("training", "全身力量 B（拉+核心）", PULL_MUSCLES + CORE_MUSCLES),
            ("training", "全身力量 C（综合强化）", PUSH_MUSCLES + PULL_MUSCLES + LEG_MUSCLES),
            ("cardio", "有氧与核心", CORE_MUSCLES),
            ("training", "上肢强化", PUSH_MUSCLES + PULL_MUSCLES),
            ("training", "下肢强化", LEG_MUSCLES),
        ]
        if safe_days == 1:
            day_indices = [2]
        elif safe_days == 2:
            day_indices = [1, 4]
        elif safe_days == 3:
            day_indices = [0, 2, 4]
        else:
            day_indices = [0, 1, 3, 4, 5, 6][:safe_days]

    for idx, day_idx in enumerate(day_indices):
        slots[day_idx] = patterns[idx % len(patterns)]
    return slots


def _pick_exercises_for_day(
    *,
    day_type: DayType,
    muscles: tuple[str, ...],
    catalog: tuple[CatalogExerciseOption, ...],
    ctx: TrainingContext,
    goal_type: GoalType,
    phase_multiplier: float,
    progress_by_id: dict[str, ExerciseProgressSummary],
    progress_by_name: dict[str, ExerciseProgressSummary],
    recent_adherence_pct: int | None,
    day_seed: int,
) -> tuple[PrescribedExercise, ...]:
    if day_type == "rest":
        return ()

    allowed_catalog_eq: set[str] = set()
    for eq in ctx.available_equipment:
        allowed_catalog_eq.update(EQUIPMENT_TO_CATALOG.get(eq, (eq,)))

    injured_areas = {item.area for item in ctx.injury_or_limitations}
    caution_muscles: set[str] = set()
    for area in injured_areas:
        caution_muscles.update(INJURY_AVOID_MUSCLES.get(area, ()))

    if day_type == "cardio":
        cardio_pool = [ex for ex in catalog if ex.exercise_type == "cardio"]
        picked = cardio_pool[day_seed % len(cardio_pool)] if cardio_pool else None
        duration = max(20, min(ctx.session_duration_min, 40))
        return (
            PrescribedExercise(
                catalog_exercise_id=picked.id if picked else None,
                name=picked.name if picked else "中等强度有氧（快走/慢跑/单车）",
                primary_muscle=picked.primary_muscle if picked else "cardiovascular",
                exercise_type="cardio",
                sets=1,
                reps=1,
                duration_min=duration,
                rest_sec=60,
                notes="保持可交谈心率区间（Zone 2）",
            ),
        )

    exercise_count = 3 if ctx.session_duration_min <= 35 else 4 if ctx.session_duration_min <= 55 else 5
    base_sets = 3 if ctx.experience_level == "beginner" else 4
    sets = max(2, min(5, round(base_sets * phase_multiplier)))
    reps = 10 if goal_type == "fat_loss" else 8 if goal_type == "muscle_gain" else 10
    rest_sec = 75 if goal_type == "fat_loss" else 105 if goal_type == "muscle_gain" else 90

    muscle_set = {m.lower() for m in muscles}
    strength_pool = [
        ex
        for ex in catalog
        if ex.exercise_type == "strength"
        and ex.primary_muscle.lower() in muscle_set
        and (not allowed_catalog_eq or ex.equipment.lower() in allowed_catalog_eq)
    ]
    # Fallback without equipment filter if catalog subset is narrow
    if len(strength_pool) < exercise_count:
        strength_pool = [
            ex for ex in catalog if ex.exercise_type == "strength" and ex.primary_muscle.lower() in muscle_set
        ]

    # Prefer compound movements first, and deprioritize muscles overlapping injury areas
    def _rank(ex: CatalogExerciseOption) -> tuple[int, int, int, str]:
        injury_penalty = 1 if ex.primary_muscle in caution_muscles else 0
        mechanic_rank = 0 if ex.mechanic == "compound" else 1
        level_rank = 0 if ex.level == ctx.experience_level else 1
        return (injury_penalty, mechanic_rank, level_rank, ex.id)

    ranked = sorted(strength_pool, key=_rank)
    chosen: list[CatalogExerciseOption] = []
    seen_muscles: set[str] = set()
    # First pass: maximize muscle variety
    for ex in ranked:
        if ex.primary_muscle not in seen_muscles:
            chosen.append(ex)
            seen_muscles.add(ex.primary_muscle)
        if len(chosen) >= exercise_count:
            break
    # Second pass: fill remaining slots
    for ex in ranked:
        if ex not in chosen:
            chosen.append(ex)
        if len(chosen) >= exercise_count:
            break

    # Safe fallback if catalog is empty (e.g. minimal unit test DB)
    if not chosen:
        fallback_names = [
            ("自重深蹲", "股四头肌"),
            ("俯卧撑", "胸肌"),
            ("哑铃划船", "中背部肌群"),
            ("平板支撑", "腹肌"),
        ][:exercise_count]
        return tuple(
            PrescribedExercise(
                catalog_exercise_id=None,
                name=name,
                primary_muscle=muscle,
                exercise_type="strength",
                sets=sets,
                reps=reps,
                rest_sec=rest_sec,
            )
            for name, muscle in fallback_names
        )

    prescribed: list[PrescribedExercise] = []
    for ex in chosen:
        prog = progress_by_id.get(ex.id) or progress_by_name.get(ex.name.strip().lower())
        suggested_weight: float | None = None
        note = ""
        if prog and prog.latest_weight_kg:
            if phase_multiplier < 0.85:
                suggested_weight = round(prog.latest_weight_kg * 0.85 * 2) / 2
                note = "减载周：维持动作标准并降低约 15% 负荷"
            elif recent_adherence_pct is not None and recent_adherence_pct >= 80:
                suggested_weight = round((prog.latest_weight_kg + 2.5) * 2) / 2
                note = f"上周完成度 {recent_adherence_pct}%，尝试渐进加重 +2.5 kg"
            else:
                suggested_weight = prog.latest_weight_kg
                note = "沿用上次有效重量，优先保证动作质量"
        if ex.primary_muscle in caution_muscles:
            caution_text = "注意已有部位限制，如出现痛感请立即减轻重量或更换动作"
            note = f"{note}；{caution_text}" if note else caution_text
        prescribed.append(
            PrescribedExercise(
                catalog_exercise_id=ex.id,
                name=ex.name,
                primary_muscle=ex.primary_muscle,
                exercise_type="strength",
                sets=sets,
                reps=reps,
                target_weight_kg=suggested_weight,
                rest_sec=rest_sec,
                notes=note,
            )
        )
    return tuple(prescribed)


def build_personalized_cycle_draft(
    *,
    user_id: str,
    goal_type: GoalType,
    start_date: date,
    duration_weeks: int,
    training_context: TrainingContext,
    catalog: tuple[CatalogExerciseOption, ...],
    exercise_progress: tuple[ExerciseProgressSummary, ...] = (),
    recent_adherence_pct: int | None = None,
    title: str | None = None,
    source: CycleSource = "deterministic",
    extra_rationale: dict[str, object] | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Deterministically build a validated multi-week periodized plan draft."""
    clamped_weeks = max(1, min(duration_weeks, 24))
    week1_monday = monday_of_week(start_date)
    phases = build_cycle_phases(clamped_weeks, goal_type)
    split = choose_split(training_context)
    weekly_slots = _schedule_day_slots(training_context.weekly_available_days, split, goal_type)

    progress_by_id = {p.catalog_exercise_id: p for p in exercise_progress if p.catalog_exercise_id}
    progress_by_name = {p.exercise_name.strip().lower(): p for p in exercise_progress}

    goal_titles = {
        "fat_loss": "减脂塑形周期",
        "muscle_gain": "增肌力量周期",
        "maintenance": "体能维持周期",
        "recomposition": "体成分重塑周期",
        "custom": "个性化训练周期",
    }
    cycle_title = title or f"{goal_titles.get(goal_type, '训练周期')} · {clamped_weeks} 周"

    warnings: list[str] = []
    if training_context.weekly_available_days >= 7:
        warnings.append("每周至少保留 1 天休息日，已自动调整为最多 6 个训练日。")
    if training_context.injury_or_limitations:
        warnings.append("已结合记录的伤病限制优先规避高负荷冲突动作，训练时仍请量力而行。")

    days_payload: list[dict[str, object]] = []
    for week_idx in range(1, clamped_weeks + 1):
        phase = next(
            (p for p in phases if p.start_week <= week_idx <= p.end_week),
            phases[-1],
        )
        for day_offset, (day_type, focus, muscles) in enumerate(weekly_slots):
            sched_date = (week1_monday + timedelta(days=(week_idx - 1) * 7 + day_offset)).isoformat()
            exercises = _pick_exercises_for_day(
                day_type=day_type,
                muscles=muscles,
                catalog=catalog,
                ctx=training_context,
                goal_type=goal_type,
                phase_multiplier=phase.volume_multiplier,
                progress_by_id=progress_by_id,
                progress_by_name=progress_by_name,
                recent_adherence_pct=recent_adherence_pct,
                day_seed=week_idx + day_offset,
            )
            days_payload.append(
                {
                    "week_index": week_idx,
                    "day_of_week": day_offset + 1,
                    "scheduled_date": sched_date,
                    "day_type": day_type,
                    "focus": focus,
                    "estimated_duration_min": None if day_type == "rest" else training_context.session_duration_min,
                    "prescribed_exercises": [ex.to_dict() for ex in exercises],
                    "nutrition_override": {},
                    "notes": f"阶段：{phase.name}" if day_type != "rest" else "注意睡眠与蛋白质摄入",
                }
            )

    rationale: dict[str, object] = {
        "split": split,
        "weekly_training_days": sum(1 for dt, _, _ in weekly_slots if dt != "rest"),
        "equipment_used": list(training_context.available_equipment),
        "experience_level": training_context.experience_level,
        "injury_count": len(training_context.injury_or_limitations),
        "recent_adherence_pct": recent_adherence_pct,
        "warnings": warnings,
    }
    if extra_rationale:
        rationale.update(extra_rationale)

    cycle_payload: dict[str, object] = {
        "title": cycle_title,
        "goal_type": goal_type,
        "start_date": week1_monday.isoformat(),
        "duration_weeks": clamped_weeks,
        "phases": [phase.to_dict() for phase in phases],
        "source": source,
        "rationale": rationale,
    }
    return cycle_payload, days_payload


def compute_day_adherence(
    day: PlanDay,
    *,
    logged_workout_dates: dict[str, int],
    today_iso: str,
) -> tuple[AdherenceStatus, int]:
    logged_count = logged_workout_dates.get(day.scheduled_date, 0)
    if day.status_override == "skipped":
        return "skipped", logged_count
    if day.day_type == "rest":
        return "rest", logged_count
    if logged_count > 0:
        return "completed", logged_count
    if day.scheduled_date < today_iso:
        return "missed", 0
    return "upcoming", 0
