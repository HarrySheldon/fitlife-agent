import * as apiModule from './api'

function v1<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    const fn = apiModule.requestV1
    if (typeof fn !== 'function') {
      return Promise.reject(new Error('API client unavailable'))
    }
    return fn<T>(path, init)
  } catch (cause) {
    return Promise.reject(cause instanceof Error ? cause : new Error('API client unavailable'))
  }
}

export interface BodyMeasurementEntry {
  id: string
  measured_date: string
  measured_at: string
  weight_kg: number | null
  body_fat_pct: number | null
  waist_cm: number | null
  chest_cm: number | null
  hip_cm: number | null
  note: string
  created_at: string
  updated_at: string
}

export interface BodyTrendPoint {
  date: string
  weight_kg: number | null
  moving_avg_7d: number | null
  body_fat_pct: number | null
  waist_cm: number | null
  chest_cm: number | null
  hip_cm: number | null
}

export interface BodyMeasurementSummary {
  count: number
  weight_count: number
  start_weight_kg: number | null
  latest_weight_kg: number | null
  latest_measured_date: string | null
  latest_7d_avg_kg: number | null
  total_change_kg: number | null
  weekly_rate_kg: number | null
  target_weight_kg: number | null
  distance_to_target_kg: number | null
  latest_body_fat_pct: number | null
  latest_waist_cm: number | null
  trend: BodyTrendPoint[]
}

export interface CreateBodyMeasurementInput {
  measured_date?: string
  weight_kg?: number | null
  body_fat_pct?: number | null
  waist_cm?: number | null
  chest_cm?: number | null
  hip_cm?: number | null
  note?: string
}

export type EquipmentId =
  | 'barbell'
  | 'dumbbell'
  | 'machine'
  | 'cable'
  | 'bodyweight'
  | 'kettlebell'
  | 'resistance_band'
  | 'cardio_machine'

export type ExperienceLevel = 'beginner' | 'intermediate' | 'advanced'
export type PreferredSplit = 'auto' | 'full_body' | 'upper_lower' | 'push_pull_legs' | 'custom'
export type InjuryArea = 'knee' | 'lower_back' | 'shoulder' | 'wrist' | 'elbow' | 'ankle' | 'hip' | 'neck' | 'other'

export interface InjuryLimitation {
  area: InjuryArea
  note: string
}

export interface TrainingContext {
  available_equipment: EquipmentId[]
  weekly_available_days: number
  session_duration_min: number
  experience_level: ExperienceLevel
  preferred_split: PreferredSplit
  injury_or_limitations: InjuryLimitation[]
  notes: string
  updated_at: string
  configured: boolean
}

export interface TrainingContextUpdateInput {
  available_equipment: EquipmentId[]
  weekly_available_days: number
  session_duration_min: number
  experience_level: ExperienceLevel
  preferred_split: PreferredSplit
  injury_or_limitations: InjuryLimitation[]
  notes: string
}

export interface ExerciseSessionPoint {
  date: string
  session_id: string
  max_weight_kg: number | null
  estimated_1rm_kg: number | null
  total_volume_kg: number
  total_sets: number
  total_reps: number
  best_set_reps: number
}

export interface ExerciseProgressSummary {
  exercise_key: string
  catalog_exercise_id: string | null
  exercise_name: string
  primary_muscle: string
  session_count: number
  latest_date: string
  best_weight_kg: number | null
  best_1rm_kg: number | null
  best_volume_kg: number
  latest_weight_kg: number | null
  latest_1rm_kg: number | null
  delta_1rm_kg: number | null
  series: ExerciseSessionPoint[]
}

export interface ProgressOverview {
  range_days: number
  today: string
  kpis: {
    latest_weight_kg: number | null
    latest_7d_avg_kg: number | null
    start_weight_kg: number | null
    target_weight_kg: number | null
    total_change_kg: number | null
    weekly_rate_kg: number | null
    distance_to_target_kg: number | null
    adherence_mode: 'weekly_frequency' | 'plan_cycle'
    adherence_completed: number
    adherence_planned: number
    adherence_pct: number
    calorie_hit_days_7d: number
    protein_hit_days_7d: number
    logged_meal_days_7d: number
    daily_calorie_target: number
    daily_protein_target: number
  }
  body_summary: BodyMeasurementSummary
  exercises: ExerciseProgressSummary[]
  calorie_trend: Array<{ date: string; value: number }>
  protein_trend: Array<{ date: string; value: number }>
  workout_count_trend: Array<{ week: string; value: number }>
  macro_distribution: Array<{ name: string; value: number }>
  training_context: TrainingContext
}

export const progressApi = {
  listBodyMeasurements: (days = 90) =>
    v1<{ entries: BodyMeasurementEntry[]; summary: BodyMeasurementSummary }>(
      `/body-measurements?days=${days}`,
    ),
  createBodyMeasurement: (payload: CreateBodyMeasurementInput) =>
    v1<{ entry: BodyMeasurementEntry; summary: BodyMeasurementSummary }>(
      '/body-measurements',
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    ),
  deleteBodyMeasurement: (id: string) =>
    v1<{ deleted: boolean; id: string }>(`/body-measurements/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  getTrainingContext: () =>
    v1<{ training_context: TrainingContext }>('/training-context'),
  updateTrainingContext: (payload: TrainingContextUpdateInput) =>
    v1<{ training_context: TrainingContext }>('/training-context', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  getExerciseProgress: (days = 90) =>
    v1<{ range_days: number; exercises: ExerciseProgressSummary[] }>(
      `/progress/exercises?days=${days}`,
    ),
  getProgressOverview: (days = 30) =>
    v1<ProgressOverview>(`/progress/overview?days=${days}`),
}
