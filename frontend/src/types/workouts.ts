export type ExerciseType = 'strength' | 'cardio'
export type WorkoutIntensity = 'low' | 'medium' | 'high'

export interface CustomExerciseValues {
  name: string
  exercise_type: ExerciseType
  primary_muscle: string
  secondary_muscles: string[]
  met: number | null
}

export interface CustomExerciseInput extends CustomExerciseValues {
  aliases: string[]
}

export interface ExerciseCatalogItem {
  id: string
  owner_user_id: string | null
  source: string
  source_name: string
  source_record_id: string
  dataset_version: string | null
  name: string
  exercise_type: ExerciseType
  primary_muscle: string
  secondary_muscles: string[]
  met: number | null
  license: string | null
  attribution: string | null
  provenance: Record<string, unknown>
  content_hash: string | null
  active: boolean
  aliases: string[]
  is_favorite: boolean
  use_count: number
  last_used_at: string | null
  rank_group: number
}

export interface StrengthSetInput {
  set_number: number
  reps: number
  load_kg: number | null
  bodyweight: boolean
}

export interface StrengthExerciseInput {
  catalog_exercise_id?: string
  custom_exercise?: CustomExerciseValues
  sets: StrengthSetInput[]
}

export interface CardioItemInput {
  catalog_exercise_id?: string
  custom_exercise?: CustomExerciseValues
  duration_min: number
  device_calories: number | null
}

export interface WorkoutDraftCreate {
  log_date: string
  title: string
  started_at: string | null
  duration_min: number | null
  intensity: WorkoutIntensity | null
  entry_method: 'form'
  strength_exercises: StrengthExerciseInput[]
  cardio_items: CardioItemInput[]
  recovery_state?: Record<string, unknown> | null
}

export interface StrengthExerciseSnapshot {
  catalog_exercise_id: string | null
  exercise_name: string
  primary_muscle: string
  secondary_muscles: string[]
  sets: StrengthSetInput[]
  provenance: Record<string, unknown>
  custom_exercise: CustomExerciseValues | null
}

export interface CardioItemSnapshot {
  catalog_exercise_id: string | null
  activity_name: string
  primary_muscle: string
  secondary_muscles: string[]
  duration_min: number
  device_calories: number | null
  met: number | null
  estimated_calories: number
  is_estimate: boolean
  estimate: Record<string, unknown>
  provenance: Record<string, unknown>
  custom_exercise: CustomExerciseValues | null
}

export interface WorkoutDraftPayload {
  log_date: string
  title: string
  started_at: string | null
  duration_min: number | null
  intensity: WorkoutIntensity | null
  entry_method: string
  weight_kg_snapshot: number
  estimated_calories: number | null
  estimate: Record<string, unknown>
  strength_exercises: StrengthExerciseSnapshot[]
  cardio_items: CardioItemSnapshot[]
  recovery_state?: Record<string, unknown> | null
}

export interface WorkoutDraft {
  id: string
  user_id: string
  payload: WorkoutDraftPayload
  version: number
  expires_at: string
  created_at: string
  updated_at: string
}

export interface ConfirmedWorkout extends Omit<WorkoutDraftPayload, 'entry_method'> {
  id: string
  user_id: string
  entry_method: string
  created_at: string
  updated_at: string
  replayed: boolean
}
