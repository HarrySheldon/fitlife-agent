"""Bound reads and fixed calculations; never expose a write-capable repository."""
import hashlib
import json
import pandas as pd
from backend.tools.meal_analyzer import analyze_meals
from backend.tools.workout_analyzer import analyze_workouts
from backend.agent.tasks.capabilities import AuthorizedTaskReads

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
EXERCISE_NAMES = frozenset({
    '深蹲', '箭步蹲', '硬拉', '腿举', '卧推', '俯卧撑', '肩推', '上斜哑铃推举',
    '划船', '引体向上', '高位下拉', '面拉',
    'squat', 'lunge', 'deadlift', 'leg press', 'bench press', 'push-up', 'push-ups',
    'shoulder press', 'incline dumbbell press', 'row', 'pull-up', 'lat pulldown', 'face pull',
})


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
