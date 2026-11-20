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

export type CycleGoalType = 'fat_loss' | 'muscle_gain' | 'maintenance' | 'recomposition' | 'custom'
export type CycleStatus = 'draft' | 'active' | 'completed' | 'archived'
export type DayAdherence = 'completed' | 'missed' | 'upcoming' | 'rest' | 'skipped'

export interface PrescribedExercise {
  catalog_exercise_id: string | null
  name: string
  primary_muscle: string
  exercise_type: 'strength' | 'cardio'
  sets: number
  reps: number
  target_weight_kg: number | null
  duration_min: number | null
  rest_sec: number
  notes: string
}

export interface CyclePhase {
  name: string
  start_week: number
  end_week: number
  focus: string
  volume_multiplier: number
}

export interface PlanDay {
  id: string
  cycle_id: string
  week_index: number
  day_of_week: number
  scheduled_date: string
  day_type: 'training' | 'rest' | 'cardio'
  focus: string
  estimated_duration_min: number | null
  prescribed_exercises: PrescribedExercise[]
  nutrition_override: Record<string, unknown>
  status_override: 'skipped' | null
  notes: string
  adherence?: DayAdherence
  logged_session_count?: number
}

export interface PlanCycle {
  id: string
  title: string
  goal_type: CycleGoalType
  start_date: string
  duration_weeks: number
  phases: CyclePhase[]
  status: CycleStatus
  source: string
  rationale: Record<string, unknown>
  version: number
  created_at: string
  updated_at: string
  activated_at: string | null
  week1_days?: PlanDay[]
}

export interface CycleAdherenceSummary {
  completed: number
  planned: number
  missed: number
  skipped: number
  pct: number
}

export interface ActivePlanCycleResponse {
  active: PlanCycle | null
  current_week: number | null
  days: PlanDay[]
  adherence: CycleAdherenceSummary | null
  drafts: PlanCycle[]
  history: PlanCycle[]
}

export interface TodayPlanResponse {
  cycle: {
    id: string
    title: string
    duration_weeks: number
    goal_type: CycleGoalType
  } | null
  day: PlanDay | null
}

export const planCycleApi = {
  getActiveCycle: (weekIndex?: number) => {
    const qs = weekIndex ? `?week_index=${weekIndex}` : ''
    return v1<ActivePlanCycleResponse>(`/plan-cycles/active${qs}`)
  },
  getTodayPlan: (date: string) =>
    v1<TodayPlanResponse>(`/plan-cycles/today?date=${encodeURIComponent(date)}`),
  createCycleDraft: (payload: {
    title?: string
    goal_type?: CycleGoalType
    duration_weeks: number
  }) =>
    v1<{ cycle: PlanCycle; week1_days: PlanDay[] }>('/plan-cycles', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  activateCycle: (cycleId: string) =>
    v1<{ cycle: PlanCycle }>(`/plan-cycles/${encodeURIComponent(cycleId)}/activate`, {
      method: 'POST',
    }),
  discardDraft: (cycleId: string) =>
    v1<{ deleted: boolean; cycle_id: string }>(`/plan-cycles/${encodeURIComponent(cycleId)}`, {
      method: 'DELETE',
    }),
  updateDay: (
    dayId: string,
    payload: {
      focus?: string
      day_type?: 'training' | 'rest' | 'cardio'
      status_override?: 'skipped'
      clear_status_override?: boolean
      notes?: string
    },
  ) =>
    v1<{ day: PlanDay }>(`/plan-cycles/days/${encodeURIComponent(dayId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  prefillWorkoutFromDay: (dayId: string) =>
    v1<{ draft_id: string; log_date: string; day_id: string }>(
      `/plan-cycles/days/${encodeURIComponent(dayId)}/prefill-workout`,
      { method: 'POST' },
    ),
}
