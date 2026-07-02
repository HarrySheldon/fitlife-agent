import type {
  ApiResponse,
  ChatResponse,
  DashboardSummary,
  EvalResult,
  GeneratedPlan,
  UserProfile,
  WeeklyReport,
} from '../types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: init?.body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
    ...init,
  })
  const payload = (await response.json()) as ApiResponse<T>
  if (!response.ok || !payload.success) {
    throw new Error(payload.message || `Request failed: ${response.status}`)
  }
  return payload.data
}

export const api = {
  dashboard: () => request<DashboardSummary>('/dashboard/summary'),
  profile: () => request<UserProfile>('/profile'),
  saveProfile: (profile: UserProfile) => request<UserProfile>('/profile', { method: 'POST', body: JSON.stringify(profile) }),
  chat: (question: string) => request<ChatResponse>('/chat', { method: 'POST', body: JSON.stringify({ question }) }),
  weeklyReport: () => request<WeeklyReport>('/report/weekly', { method: 'POST' }),
  generatePlan: () => request<GeneratedPlan>('/plan/generate', { method: 'POST' }),
  runEval: (limit = 20) => request<EvalResult>('/eval/run', { method: 'POST', body: JSON.stringify({ limit }) }),
  upload: (kind: 'meals' | 'workouts', file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<{ filename: string; bytes: number }>(`/upload/${kind}`, { method: 'POST', body: form })
  },
}
