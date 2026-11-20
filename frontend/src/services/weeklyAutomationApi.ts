import * as apiModule from './api'
import type { CycleGoalType, PlanCycle, PlanDay } from './planCycleApi'

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

export interface WeeklyAutomationRun {
  iso_week: string
  report_week: string
  report_status: 'generated' | 'already_exists' | 'failed'
  draft_cycle_id: string | null
  draft_status: 'generated_agent' | 'generated_deterministic' | 'already_exists' | 'skipped' | 'failed'
  message: string
  dismissed: boolean
  created_at: string
}

export const weeklyAutomationApi = {
  check: () =>
    v1<{ run: WeeklyAutomationRun }>('/weekly-automation/check', {
      method: 'POST',
    }),
  status: () =>
    v1<{ run: WeeklyAutomationRun | null }>('/weekly-automation/status'),
  dismiss: (isoWeek?: string) =>
    v1<{ dismissed: boolean; iso_week: string }>('/weekly-automation/dismiss', {
      method: 'POST',
      body: JSON.stringify({ iso_week: isoWeek ?? null }),
    }),
  generatePersonalizedDraft: (payload: {
    title?: string
    goal_type?: CycleGoalType
    duration_weeks?: number
    focus_note?: string
  }) =>
    v1<{ cycle: PlanCycle; week1_days: PlanDay[] }>('/plan-cycles/generate-personalized', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}
