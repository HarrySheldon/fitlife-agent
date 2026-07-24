import type {
  AccountDeleteRequest,
  AccountPasswordChangeRequest,
  AccountDataExport,
  AgentEntryResponse,
  ApiResponse,
  AuthRequest,
  AuthSession,
  AuthenticatedUser,
  ChatResponse,
  CoachActionRequest,
  CoachActionResponse,
  ConfirmTargetsInput,
  DailyDetail,
  DailySummary,
  DailyTargetValues,
  DailyTargetVersion,
  DashboardSummary,
  EvalResult,
  GeneratedPlan,
  MealRecord,
  ModelConnectionSettings,
  ModelConnectionTestResult,
  ModelSettingsUpdate,
  OverallGoalVersion,
  OverallGoalVersionUpdate,
  ProfileSetup,
  ProfileSetupMutation,
  ProfileVersionUpdate,
  ProcessingMode,
  TargetPreview,
  TodayOverview,
  TrainingPersonalizationUpdate,
  UserProfile,
  UserPreferences,
  UserPreferencesUpdate,
  WeeklyReport,
  WorkoutRecord,
} from '../types'
import i18n from '../i18n'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'
const API_V1_BASE = import.meta.env.VITE_API_V1_BASE_URL || '/api/v1'
const TOKEN_KEY = 'fitlife_access_token'
const ACCOUNT_EXPORT_FILENAME = 'account-data-export.zip'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return requestFrom<T>(API_BASE, path, init)
}

async function requestV1<T>(path: string, init?: RequestInit): Promise<T> {
  return requestFrom<T>(API_V1_BASE, path, init)
}

async function requestFrom<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  const headers = requestHeaders(init)

  const response = await fetch(`${base}${path}`, {
    ...init,
    headers,
  })
  const payload = (await response.json().catch(() => ({}))) as Partial<ApiResponse<T>> & { detail?: string }
  if (!response.ok || !payload.success) {
    throw responseError(response, payload)
  }
  return payload.data as T
}

async function requestAccountExport(): Promise<AccountDataExport> {
  const response = await fetch(`${API_BASE}/account/export`, { headers: requestHeaders() })
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as Partial<ApiResponse<unknown>> & { detail?: string }
    throw responseError(response, payload)
  }

  const disposition = response.headers.get('Content-Disposition')
  const serverFilename = disposition?.match(/filename="?([^";]+)"?/i)?.[1]
  return {
    blob: await response.blob(),
    filename: serverFilename === ACCOUNT_EXPORT_FILENAME ? serverFilename : ACCOUNT_EXPORT_FILENAME,
  }
}

function requestHeaders(init?: RequestInit): Headers {
  const token = tokenStorage.get()
  const headers = new Headers(init?.headers)
  headers.set('Accept-Language', languageStorage.get())
  headers.set('X-Timezone', browserTimezone())
  if (!(init?.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return headers
}

function responseError(
  response: Response,
  payload: Partial<ApiResponse<unknown>> & { detail?: string },
): ApiRequestError {
  const message = payload.error?.message
    || payload.message
    || payload.detail
    || i18n.t('common.requestFailed', { lng: languageStorage.get(), status: response.status })
  return new ApiRequestError(message, payload.error?.code, payload.processing_mode, response.status)
}

export class ApiRequestError extends Error {
  constructor(
    message: string,
    public readonly code?: string,
    public readonly processingMode?: ProcessingMode,
    public readonly status?: number,
  ) {
    super(message)
    this.name = 'ApiRequestError'
  }
}

export const api = {
  register: (payload: AuthRequest) => request<AuthSession>('/auth/register', { method: 'POST', body: JSON.stringify(payload) }),
  login: (payload: AuthRequest) => request<AuthSession>('/auth/login', { method: 'POST', body: JSON.stringify(payload) }),
  me: () => request<AuthenticatedUser>('/auth/me'),
  changePassword: (payload: AccountPasswordChangeRequest) =>
    request<AuthSession>('/account/password/change', { method: 'POST', body: JSON.stringify(payload) }),
  revokeOtherSessions: () => request<AuthSession>('/account/sessions/revoke-others', { method: 'POST' }),
  exportAccountData: requestAccountExport,
  deleteAccount: async (payload: AccountDeleteRequest) => {
    await request<null>('/account', { method: 'DELETE', body: JSON.stringify(payload) })
  },
  preferences: () => request<UserPreferences>('/settings/preferences'),
  updatePreferences: (preferences: UserPreferencesUpdate) =>
    request<UserPreferences>('/settings/preferences', { method: 'PATCH', body: JSON.stringify(preferences) }),
  dashboard: () => request<DashboardSummary>('/dashboard/summary'),
  dashboardForDate: (date: string) => request<DashboardSummary>(`/dashboard/summary?date=${encodeURIComponent(date)}`),
  profile: () => request<UserProfile>('/profile'),
  saveTrainingPersonalization: (update: TrainingPersonalizationUpdate) =>
    request<UserProfile>('/profile/personalization', { method: 'PATCH', body: JSON.stringify(update) }),
  profileSetup: () => requestV1<ProfileSetup>('/profile'),
  saveProfileVersion: (profile: ProfileVersionUpdate) =>
    requestV1<ProfileSetupMutation>('/profile', { method: 'PUT', body: JSON.stringify(profile) }),
  overallGoal: () => requestV1<{ overall: OverallGoalVersion | null }>('/goals'),
  saveOverallGoal: (goal: OverallGoalVersionUpdate) =>
    requestV1<ProfileSetupMutation>('/goals/overall', { method: 'PUT', body: JSON.stringify(goal) }),
  calculateTargets: (manualTargets?: DailyTargetValues) =>
    requestV1<TargetPreview>('/targets/calculate', {
      method: 'POST',
      body: JSON.stringify(manualTargets ? { manual_targets: manualTargets } : {}),
    }),
  confirmTargets: ({ idempotencyKey, ...payload }: ConfirmTargetsInput) =>
    requestV1<{ target: DailyTargetVersion }>('/targets/confirm', {
      method: 'POST',
      headers: {
        'If-Match': payload.preview.preview_token,
        'Idempotency-Key': idempotencyKey,
      },
      body: JSON.stringify(payload),
    }),
  targetHistory: () => requestV1<DailyTargetVersion[]>('/targets/history'),
  modelSettings: () => request<ModelConnectionSettings>('/settings/model'),
  saveModelSettings: (settings: ModelSettingsUpdate) =>
    request<ModelConnectionSettings>('/settings/model', { method: 'PUT', body: JSON.stringify(settings) }),
  clearModelApiKey: () => request<ModelConnectionSettings>('/settings/model/api-key', { method: 'DELETE' }),
  listModels: () => request<{ models: string[] }>('/settings/model/models', { method: 'POST' }),
  testModelConnection: () => request<ModelConnectionTestResult>('/settings/model/test', { method: 'POST' }),
  chat: (question: string) => request<ChatResponse>('/chat', { method: 'POST', body: JSON.stringify({ question }) }),
  today: (date: string) => request<TodayOverview>(`/today?date=${encodeURIComponent(date)}`),
  coachAction: (payload: CoachActionRequest) =>
    request<CoachActionResponse>('/coach/action', { method: 'POST', body: JSON.stringify(payload) }),
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

const LANGUAGE_KEY = 'fitlife_language'

export const languageStorage = {
  get: (): 'en-US' | 'zh-CN' => window.localStorage.getItem(LANGUAGE_KEY) === 'zh-CN' ? 'zh-CN' : 'en-US',
  set: (language: 'en-US' | 'zh-CN') => window.localStorage.setItem(LANGUAGE_KEY, language),
}

export function browserTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
}
