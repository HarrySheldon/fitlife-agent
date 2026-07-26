import type {
  ExerciseCatalogItem,
  WorkoutDraftCreate,
  WorkoutIntensity,
} from '../types/workouts'

export interface StrengthSetForm {
  reps: string
  load: string
  bodyweight: boolean
}

export interface SelectedStrengthExercise {
  key: string
  exercise: ExerciseCatalogItem
  setCount: string
  reps: string
  load: string
  bodyweight: boolean
  expanded: boolean
  setRows: StrengthSetForm[]
}

export interface SelectedCardioExercise {
  key: string
  exercise: ExerciseCatalogItem
  duration: string
  deviceCalories: string
}

export interface WorkoutSessionForm {
  logDate: string
  title: string
  startedAt: string
  duration: string
  intensity: WorkoutIntensity | ''
}

export function newStrengthExercise(exercise: ExerciseCatalogItem): SelectedStrengthExercise {
  return {
    key: `strength:${exercise.id}`,
    exercise,
    setCount: '',
    reps: '',
    load: '',
    bodyweight: false,
    expanded: false,
    setRows: [],
  }
}

export function newCardioExercise(exercise: ExerciseCatalogItem): SelectedCardioExercise {
  return {
    key: `cardio:${exercise.id}`,
    exercise,
    duration: '',
    deviceCalories: '',
  }
}

export function resizeSetRows(
  current: StrengthSetForm[],
  countValue: string,
  defaults: Pick<StrengthSetForm, 'reps' | 'load' | 'bodyweight'>,
): StrengthSetForm[] {
  const count = positiveInteger(countValue)
  if (count === null) return []
  return Array.from({ length: count }, (_, index) => current[index] ?? { ...defaults })
}

export function workoutDraftInput(
  session: WorkoutSessionForm,
  strength: SelectedStrengthExercise[],
  cardio: SelectedCardioExercise[],
): WorkoutDraftCreate {
  return {
    log_date: session.logDate,
    title: session.title.trim(),
    started_at: session.startedAt
      ? `${session.logDate}T${session.startedAt}:00`
      : null,
    duration_min: optionalPositiveNumber(session.duration),
    intensity: session.intensity || null,
    entry_method: 'form',
    strength_exercises: strength.map((item) => ({
      catalog_exercise_id: item.exercise.id,
      sets: strengthSets(item),
    })),
    cardio_items: cardio.map((item) => ({
      catalog_exercise_id: item.exercise.id,
      duration_min: requiredPositiveNumber(item.duration),
      device_calories: optionalNonNegativeNumber(item.deviceCalories),
    })),
  }
}

export function isWorkoutComplete(
  session: WorkoutSessionForm,
  strength: SelectedStrengthExercise[],
  cardio: SelectedCardioExercise[],
): boolean {
  if (!session.title.trim() || strength.length + cardio.length === 0) return false
  if (session.duration && optionalPositiveNumber(session.duration) === null) return false
  if (session.duration && !session.intensity) return false
  return strength.every(validStrength) && cardio.every((item) => (
    positiveNumber(item.duration) !== null
    && (!item.deviceCalories || nonNegativeNumber(item.deviceCalories) !== null)
    && !cardioNeedsEnergySource(item)
  ))
}

export function cardioNeedsEnergySource(item: SelectedCardioExercise): boolean {
  return item.exercise.met == null && !item.deviceCalories.trim()
}

function validStrength(item: SelectedStrengthExercise): boolean {
  const count = positiveInteger(item.setCount)
  if (count === null) return false
  const sets = item.expanded
    ? resizeSetRows(item.setRows, item.setCount, item)
    : Array.from({ length: count }, () => item)
  return sets.every((set) => (
    positiveInteger(set.reps) !== null
    && (set.bodyweight || !set.load || nonNegativeNumber(set.load) !== null)
  ))
}

function strengthSets(item: SelectedStrengthExercise) {
  const count = requiredPositiveInteger(item.setCount)
  const rows = item.expanded
    ? resizeSetRows(item.setRows, item.setCount, item)
    : Array.from({ length: count }, () => ({
      reps: item.reps,
      load: item.load,
      bodyweight: item.bodyweight,
    }))
  return rows.map((set, index) => ({
    set_number: index + 1,
    reps: requiredPositiveInteger(set.reps),
    load_kg: set.bodyweight ? null : optionalNonNegativeNumber(set.load),
    bodyweight: set.bodyweight,
  }))
}

function positiveInteger(value: string): number | null {
  if (!/^[1-9]\d*$/.test(value)) return null
  return Number(value)
}

function requiredPositiveInteger(value: string): number {
  const parsed = positiveInteger(value)
  if (parsed === null) throw new Error('WORKOUT_POSITIVE_INTEGER_REQUIRED')
  return parsed
}

function positiveNumber(value: string): number | null {
  if (!value.trim()) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

function requiredPositiveNumber(value: string): number {
  const parsed = positiveNumber(value)
  if (parsed === null) throw new Error('WORKOUT_POSITIVE_NUMBER_REQUIRED')
  return parsed
}

function optionalPositiveNumber(value: string): number | null {
  return value.trim() ? positiveNumber(value) : null
}

function nonNegativeNumber(value: string): number | null {
  if (!value.trim()) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null
}

function optionalNonNegativeNumber(value: string): number | null {
  return value.trim() ? nonNegativeNumber(value) : null
}
