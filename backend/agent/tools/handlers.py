"""Bound reads and fixed calculations; never expose a write-capable repository."""
from datetime import date
import hashlib
import json
import pandas as pd
from backend.tools.meal_analyzer import analyze_meals
from backend.tools.workout_analyzer import analyze_workouts
from backend.agent.tasks.capabilities import AuthorizedTaskReads
from backend.domain.body_measurements import compute_body_summary
from backend.domain.plan_adjustment import EXERCISE_NAMES
from backend.domain.plan_cycles import EQUIPMENT_TO_CATALOG

PROFILE_FIELDS = {
    'experience_level': 'training', 'training_preference': 'training',
    'weekly_training_frequency': 'training', 'goal': 'profile',
    'daily_calorie_target': 'diet', 'daily_protein_target': 'diet',
    'allergies_or_restrictions': 'diet', 'diet_preferences': 'diet',
}
RECORD_FIELDS = {
    'training': frozenset({'date', 'type', 'exercise', 'muscle_group', 'sets', 'reps', 'weight', 'duration_min'}),
    'diet': frozenset({'date', 'meal', 'food', 'amount', 'unit', 'calories', 'protein', 'carbs', 'fat'}),
}

# Reviewed exercise vocabulary, aligned with knowledge_base/exercise_library.md.
# Extending content does not require a new per-exercise tool or workflow.
# The list lives in the domain module so plan patches and the calculate tool
# cannot drift apart.


class BoundFitnessReads:
    def __init__(self, repository, owner_id):
        if not owner_id:
            raise PermissionError('AUTHENTICATED_OWNER_REQUIRED')
        self.owner_id = owner_id
        self._profile = lambda: repository.read_profile(owner_id)
        self._training = lambda domains: AuthorizedTaskReads(repository, owner_id, frozenset(domains)).read_workouts()
        self._diet = lambda domains: AuthorizedTaskReads(repository, owner_id, frozenset(domains)).read_meals()

    def query(self, args, domains):
        fields = set(args.fields)
        if args.domain == 'profile':
            if any(key not in PROFILE_FIELDS or PROFILE_FIELDS[key] not in domains for key in fields):
                raise PermissionError('FIELD_NOT_AUTHORIZED')
            profile = self._profile().model_dump()
            return {key: profile[key] for key in args.fields if key in profile}
        if not fields <= RECORD_FIELDS[args.domain]:
            raise PermissionError('FIELD_NOT_AUTHORIZED')
        frame = self._training(domains) if args.domain == 'training' else self._diet(domains)
        dates = pd.to_datetime(frame['date'], errors='coerce').dt.date
        frame = frame.loc[(dates >= args.start_date) & (dates <= args.end_date)]
        if len(frame) > 200:
            raise ValueError('RESULT_TOO_LARGE')
        return frame[args.fields].where(pd.notna(frame[args.fields]), None).to_dict(orient='records')

    def query_progress(self, args, domains):
        """Read-only owner-scoped progress metrics (body trend, exercise PRs, adherence, training context)."""
        from backend.infrastructure.postgres.runtime import get_database
        from backend.infrastructure.repositories.postgres_body_measurement_repository import (
            PostgresBodyMeasurementRepository,
        )
        from backend.infrastructure.repositories.postgres_exercise_progress_repository import (
            PostgresExerciseProgressRepository,
        )
        from backend.infrastructure.repositories.postgres_plan_cycle_repository import (
            PostgresPlanCycleRepository,
        )
        from backend.infrastructure.repositories.postgres_training_context_repository import (
            PostgresTrainingContextRepository,
        )

        db = get_database()
        today_iso = date.today().isoformat()
        if args.aspect == 'body_trend':
            if 'profile' not in domains:
                raise PermissionError('SCOPE_PERMISSION_REQUIRED')
            entries = PostgresBodyMeasurementRepository(db).list_for_user(
                self.owner_id, days=args.days, end_date=today_iso
            )
            target_weight = None
            try:
                prof = self._profile()
                target_weight = float(prof.target_weight_kg) if prof.target_weight_kg else None
            except Exception:
                pass
            summary = compute_body_summary(entries, target_weight_kg=target_weight).to_dict()
            summary['trend'] = summary['trend'][-14:]
            return summary
        if args.aspect == 'training_context':
            if not {'profile', 'training'} <= domains:
                raise PermissionError('SCOPE_PERMISSION_REQUIRED')
            return PostgresTrainingContextRepository(db).get(self.owner_id).to_dict()
        if args.aspect == 'exercise_progress':
            if 'training' not in domains:
                raise PermissionError('SCOPE_PERMISSION_REQUIRED')
            items = PostgresExerciseProgressRepository(db).list_progress(
                self.owner_id, days=args.days, end_date=today_iso
            )
            return [
                {
                    'exercise_name': item.exercise_name,
                    'primary_muscle': item.primary_muscle,
                    'session_count': item.session_count,
                    'latest_date': item.latest_date,
                    'best_weight_kg': item.best_weight_kg,
                    'best_1rm_kg': item.best_1rm_kg,
                    'delta_1rm_kg': item.delta_1rm_kg,
                }
                for item in items[:15]
            ]
        if args.aspect == 'plan_adherence':
            if 'training' not in domains:
                raise PermissionError('SCOPE_PERMISSION_REQUIRED')
            repo = PostgresPlanCycleRepository(db)
            active = repo.get_active_cycle(self.owner_id)
            adherence = repo.week_adherence_summary(self.owner_id, today_iso)
            return {
                'active_cycle': active.to_dict() if active else None,
                'week_adherence': adherence,
            }
        raise ValueError('UNKNOWN_PROGRESS_ASPECT')


def search_public_foods(query: str, limit: int = 8) -> list[dict]:
    """Read-only search over the public food catalog (never exposes user private items)."""
    from backend.infrastructure.repositories.postgres_food_catalog_repository import (
        PostgresFoodCatalogRepository,
    )
    from backend.infrastructure.postgres.runtime import get_database

    repo = PostgresFoodCatalogRepository(get_database())
    items = repo.search('__public_only__', query, limit=limit)
    public_items = [item for item in items if item.owner_user_id is None][:limit]
    return [
        {
            'id': item.id,
            'name': item.name,
            'basis': f'{item.basis_amount:g} {item.unit} ({item.basis_type})',
            'calories': round(item.calories, 1),
            'protein_g': round(item.protein, 1),
            'carbs_g': round(item.carbs, 1),
            'fat_g': round(item.fat, 1),
            'aliases': list(item.aliases[:3]),
        }
        for item in public_items
    ]


def search_public_exercises(
    *,
    query: str = '',
    muscle_group: str | None = None,
    equipment: str | None = None,
    exercise_type: str = 'any',
    limit: int = 8,
) -> list[dict]:
    """Read-only structured search over the public exercise catalog."""
    from backend.infrastructure.postgres.runtime import get_database

    db = get_database()
    where = ["active = 1", "owner_user_id IS NULL"]
    params: list[object] = []
    if exercise_type in ('strength', 'cardio'):
        where.append("exercise_type = ?")
        params.append(exercise_type)
    if muscle_group:
        where.append("(lower(primary_muscle) LIKE ? OR lower(secondary_muscles_json) LIKE ?)")
        like_m = f"%{muscle_group.strip().lower()}%"
        params.extend([like_m, like_m])
    if query.strip():
        where.append(
            "(lower(name) LIKE ? OR id IN (SELECT exercise_id FROM catalog_aliases WHERE exercise_id IS NOT NULL AND normalized_alias LIKE ?))"
        )
        like_q = f"%{query.strip().lower()}%"
        params.extend([like_q, like_q])

    allowed_eq: set[str] | None = None
    if equipment:
        eq_key = equipment.strip().lower()
        allowed_eq = set(EQUIPMENT_TO_CATALOG.get(eq_key, (eq_key,)))

    with db.connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, name, exercise_type, primary_muscle, provenance_json
            FROM exercise_catalog
            WHERE {' AND '.join(where)}
            ORDER BY id ASC
            LIMIT ?
            """,
            (*params, max(limit * 6, 60)),
        ).fetchall()

    results: list[dict] = []
    for row in rows:
        prov: dict[str, object] = {}
        try:
            parsed = json.loads(row['provenance_json'] or '{}')
            if isinstance(parsed, dict):
                prov = parsed
        except json.JSONDecodeError:
            pass
        row_eq = str(prov.get('equipment') or '').lower()
        if allowed_eq is not None and row_eq not in allowed_eq:
            continue
        loc = prov.get('localization') if isinstance(prov.get('localization'), dict) else {}
        instructions = loc.get('instructions') if isinstance(loc, dict) else prov.get('instructions')
        summary = instructions[0][:160] if isinstance(instructions, list) and instructions else ''
        results.append(
            {
                'id': row['id'],
                'name': row['name'],
                'exercise_type': row['exercise_type'],
                'primary_muscle': row['primary_muscle'],
                'equipment': row_eq or 'body only',
                'mechanic': str(prov.get('mechanic') or ''),
                'level': str(prov.get('level') or ''),
                'cue': summary,
            }
        )
        if len(results) >= limit:
            break
    return results


def version_of(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def calculate(args, get_evidence, language):
    if args.operation == 'validate_training':
        if any(item.name.strip().lower() not in EXERCISE_NAMES for item in args.exercises):
            raise ValueError('UNKNOWN_EXERCISE')
        exercises = [item.model_dump() for item in args.exercises]
        if language == 'zh-CN':
            lines = ['建议训练安排（非已完成记录）：'] + [
                f"- {item.name}：{item.sets} 组 × {item.reps} 次；组间休息 {item.rest_seconds} 秒。"
                for item in args.exercises]
        else:
            lines = ['Suggested workout (not a recorded activity):'] + [
                f'- {item.name}: {item.sets} sets × {item.reps} reps; rest {item.rest_seconds} seconds.'
                for item in args.exercises]
        return {'kind': 'suggestion', 'exercises': exercises, 'suggestion_markdown': '\n'.join(lines),
                'formula_version': 'training-shape-v1', 'clinical_safety_certified': False}
    records = get_evidence(args.input_ref)
    expected_domain = 'training' if args.operation == 'workout_analysis' else 'diet'
    if records['tool'] != 'fitness.query' or records['domain'] != expected_domain:
        raise PermissionError('EVIDENCE_SCOPE_MISMATCH')
    frame = pd.DataFrame(records['data'], columns=records.get('fields'))
    if args.operation == 'workout_analysis':
        return analyze_workouts(frame)
    targets = get_evidence(args.targets_ref)
    if targets['tool'] != 'fitness.query' or targets['domain'] != 'profile':
        raise PermissionError('EVIDENCE_SCOPE_MISMATCH')
    profile = targets['data']
    return analyze_meals(frame, calorie_target=profile['daily_calorie_target'],
                         protein_target=profile['daily_protein_target'])
