import type {
  AgentEntryResponse,
  ApiResponse,
  AuthRequest,
  AuthSession,
  AuthenticatedUser,
  ChatResponse,
  DailyDetail,
  DailySummary,
  DashboardSummary,
  EvalResult,
  GeneratedPlan,
  MealRecord,
  UserProfile,
  WeeklyReport,
  WorkoutRecord,
} from '../types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'
const TOKEN_KEY = 'fitlife_access_token'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = tokenStorage.get()
  const headers = new Headers(init?.headers)
  if (!(init?.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  })
  const payload = (await response.json().catch(() => ({}))) as Partial<ApiResponse<T>> & { detail?: string }
  if (!response.ok || !payload.success) {
    throw new Error(payload.message || payload.detail || `Request failed: ${response.status}`)
  }
  return payload.data as T
}

export const api = {
  register: (payload: AuthRequest) => request<AuthSession>('/auth/register', { method: 'POST', body: JSON.stringify(payload) }),
  login: (payload: AuthRequest) => request<AuthSession>('/auth/login', { method: 'POST', body: JSON.stringify(payload) }),
  me: () => request<AuthenticatedUser>('/auth/me'),
  dashboard: () => request<DashboardSummary>('/dashboard/summary'),
  dashboardForDate: (date: string) => request<DashboardSummary>(`/dashboard/summary?date=${encodeURIComponent(date)}`),
  profile: () => request<UserProfile>('/profile'),
  saveProfile: (profile: UserProfile) => request<UserProfile>('/profile', { method: 'POST', body: JSON.stringify(profile) }),
  chat: (question: string) => request<ChatResponse>('/chat', { method: 'POST', body: JSON.stringify({ question }) }),
  weeklyReport: () => request<WeeklyReport>('/report/weekly', { method: 'POST' }),
  generatePlan: () => request<GeneratedPlan>('/plan/generate', { method: 'POST' }),
  runEval: (limit = 20) => request<EvalResult>('/eval/run', { method: 'POST', body: JSON.stringify({ limit }) }),
  calendarDays: (start: string, end: string) => request<DailySummary[]>(`/calendar/days?start=${start}&end=${end}`),
  calendarDay: (date: string) => request<DailyDetail>(`/calendar/day/${date}`),
  addMeal: (record: MealRecord) => request<DailyDetail>('/calendar/meals', { method: 'POST', body: JSON.stringify(record) }),
  addWorkout: (record: WorkoutRecord) =>
    request<DailyDetail>('/calendar/workouts', { method: 'POST', body: JSON.stringify(record) }),
  addAgentEntry: (date: string, text: string) =>
    request<AgentEntryResponse>('/calendar/agent-entry', { method: 'POST', body: JSON.stringify({ date, text }) }),
  upload: (kind: 'meals' | 'workouts', file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<{ filename: string; bytes: number }>(`/upload/${kind}`, { method: 'POST', body: form })
  },
}

export const tokenStorage = {
  get: () => window.localStorage.getItem(TOKEN_KEY),
  set: (token: string) => window.localStorage.setItem(TOKEN_KEY, token),
  clear: () => window.localStorage.removeItem(TOKEN_KEY),
}
