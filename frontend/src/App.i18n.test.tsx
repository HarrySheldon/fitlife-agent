import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from './i18n'
import { AppRoutes } from './routes/AppRoutes'
import { api } from './services/api'
import type { EvalResult } from './types'


const state = vi.hoisted(() => ({
  authenticated: true,
  language: 'en-US' as 'en-US' | 'zh-CN',
  todayLoading: false,
  todayError: null as string | null,
}))

const profile = {
  height_cm: 175, weight_kg: 72, age: 30, gender: 'male' as const, goal: 'maintenance' as const,
  weekly_training_frequency: 3, diet_preferences: [], allergies_or_restrictions: [], target_weight_kg: 72,
  daily_calorie_target: 2200, daily_protein_target: 130, experience_level: 'novice' as const,
  training_preference: 'mixed' as const, target_mode: 'suggested' as const,
}

const emptyDay = {
  summary: { date: '2026-07-14', calories: 0, protein: 0, carbs: 0, fat: 0, meal_count: 0, training_sessions: 0, training_duration_min: 0, has_data: false },
  meals: [],
  workouts: [],
}

const failedEvaluation: EvalResult = {
  total_tests: 2,
  pass_rate: 0.5,
  tool_call_success_rate: 1,
  retrieval_hit_rate: 0.5,
  structured_output_success_rate: 1,
  preference_compliance_rate: 0.5,
  validator_pass_rate: 1,
  group_metrics: {
    by_expected_tool: { analyze_meals: { total: 2, pass_rate: 0.5 } },
    by_retrieval_requirement: { requires_retrieval: { total: 2, pass_rate: 0.5 } },
  },
  failed_cases: [{
    question: 'Agent-provided evaluation question',
    expected_tool: 'analyze_meals',
    expected_retrieval_doc: null,
    passed: false,
    tool_ok: true,
    retrieval_ok: false,
    structured_ok: true,
    keywords_ok: true,
    validator_ok: true,
    checks: [{ name: 'retrieval', passed: false, expected: true, observed: false, reason: 'Agent-provided failure reason' }],
    failure_reasons: ['Agent-provided failure reason'],
    trace: {},
  }],
  cases: [],
}

vi.mock('./hooks/useAuth', () => ({
  useAuth: () => ({
    user: state.authenticated ? { user_id: 'user-1', username: 'user', email: null, phone: null, display_name: 'User Record' } : null,
    initializing: false,
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
  }),
}))

vi.mock('./hooks/usePreferences', () => ({
  usePreferences: () => ({
    preferences: { language: state.language, unit_system: 'metric', timezone: 'UTC' },
    loading: false,
    error: null,
    updatePreferences: vi.fn(),
    localDate: () => '2026-07-14',
  }),
}))

vi.mock('./hooks/useToday', () => ({
  useToday: () => ({
    data: state.todayLoading ? null : { ...emptyDay, date: '2026-07-14', targets: [], coach_actions: ['explain_today'] },
    loading: state.todayLoading,
    error: state.todayError,
    refresh: vi.fn(),
  }),
}))

vi.mock('./hooks/useDashboard', () => ({
  useDashboard: () => ({
    data: {
      summary_date: '2026-07-14', today_calories: 0, today_protein: 0,
      weekly_training_count: 0, weekly_training_duration_min: 0,
      calorie_trend: [], protein_trend: [], workout_count_trend: [], macro_distribution: [],
      meal_summary: '', workout_summary: '',
    },
    loading: false,
    error: null,
  }),
}))

vi.mock('./hooks/useProfile', () => ({
  useProfile: () => ({ profile, setProfile: vi.fn(), loading: false, saving: false, error: null, save: vi.fn() }),
}))

vi.mock('./hooks/useProfileSetup', () => ({
  useProfileSetup: () => ({
    setup: { profile: {}, goal: {}, target: {}, setup_complete: true },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}))

vi.mock('./hooks/useModelSettings', () => ({
  useModelSettings: () => ({
    settings: {
      provider: 'openai', protocol: 'responses', base_url: null, model: 'gpt-5.5', enabled: false,
      api_key_configured: false, api_key_hint: null, test_status: 'untested', test_error_code: null,
      tested_at: null, updated_at: null, state: 'unconfigured',
    },
    models: [], loading: false, action: null, feedback: null, refresh: vi.fn(), save: vi.fn(),
    clearApiKey: vi.fn(), listModels: vi.fn(), testConnection: vi.fn(),
  }),
}))

function renderRoute(route: string) {
  return render(<MemoryRouter initialEntries={[route]}><AppRoutes /></MemoryRouter>)
}

beforeEach(async () => {
  vi.restoreAllMocks()
  state.authenticated = true
  state.todayLoading = false
  state.todayError = null
  vi.spyOn(api, 'calendarDays').mockResolvedValue([])
  vi.spyOn(api, 'calendarDay').mockResolvedValue(emptyDay)
  await i18n.changeLanguage(state.language)
})

describe.each([
  {
    language: 'en-US' as const,
    routes: [
      ['/login', 'Create your fitness workspace'], ['/', 'Today'], ['/logbook', 'Logbook'],
      ['/review', 'Review'], ['/plan', 'Plan'], ['/profile', 'Profile'], ['/evaluation', 'Agent evaluation'],
      ['/settings', 'Settings'], ['/settings/general', 'General settings'], ['/settings/model', 'Model connection'],
    ],
    navigation: ['Today', 'Logbook', 'Review', 'Plan', 'Profile', 'Settings'],
  },
  {
    language: 'zh-CN' as const,
    routes: [
      ['/login', '创建你的健身空间'], ['/', '今天'], ['/logbook', '日志'],
      ['/review', '复盘'], ['/plan', '计划'], ['/profile', '个人资料'], ['/evaluation', 'Agent 评测'],
      ['/settings', '设置'], ['/settings/general', '通用设置'], ['/settings/model', '模型连接'],
    ],
    navigation: ['今天', '日志', '复盘', '计划', '个人资料', '设置'],
  },
])('$language route coverage', ({ language, routes, navigation }) => {
  it.each(routes)('localizes %s', async (route, heading) => {
    state.language = language
    state.authenticated = route !== '/login'
    await i18n.changeLanguage(language)

    renderRoute(route)

    expect(await screen.findByRole('heading', { level: route === '/login' ? 2 : 1, name: heading })).toBeInTheDocument()
  })

  it('localizes the complete primary navigation', async () => {
    state.language = language
    await i18n.changeLanguage(language)
    renderRoute('/')

    for (const label of navigation) {
      expect(screen.getByRole('link', { name: label })).toBeInTheDocument()
    }
  })
})

it('localizes loading, empty, and validation states in Chinese', async () => {
  state.language = 'zh-CN'
  state.todayLoading = true
  await i18n.changeLanguage('zh-CN')
  const { unmount } = renderRoute('/')
  expect(screen.getByText('正在加载今天...')).toBeInTheDocument()
  unmount()

  state.todayLoading = false
  renderRoute('/')
  expect(await screen.findByText('尚未记录餐食')).toBeInTheDocument()
  expect(screen.getByText('尚未记录训练')).toBeInTheDocument()
})

it.each([
  ['en-US' as const, 'Username, email, or phone is required'],
  ['zh-CN' as const, '请输入用户名、邮箱或手机号'],
])('renders the registration validation state in %s', async (language, expected) => {
  state.language = language
  state.authenticated = false
  await i18n.changeLanguage(language)
  renderRoute('/login')

  const submit = screen.getByRole('button', {
    name: language === 'en-US' ? 'Create account' : '创建账号',
  })
  fireEvent.submit(submit.closest('form')!)

  expect(await screen.findByText(expected)).toBeInTheDocument()
})

it.each([
  ['en-US' as const, failedEvaluation, '1 of 2 cases failed', 'Expected tool', 'Analyze meals'],
  ['zh-CN' as const, failedEvaluation, '2 个用例中有 1 个失败', '预期工具', '分析餐食'],
  ['en-US' as const, { ...failedEvaluation, failed_cases: [], pass_rate: 1 }, 'All 2 cases passed', 'Expected tool', 'Analyze meals'],
  ['zh-CN' as const, { ...failedEvaluation, failed_cases: [], pass_rate: 1 }, '全部 2 个用例通过', '预期工具', '分析餐食'],
])('renders actual evaluation results in %s', async (language, result, summary, group, tool) => {
  state.language = language
  await i18n.changeLanguage(language)
  vi.spyOn(api, 'runEval').mockResolvedValue(result)
  renderRoute('/evaluation')

  fireEvent.click(screen.getByRole('button', {
    name: language === 'en-US' ? 'Run eval' : '运行评测',
  }))

  expect(await screen.findByText(summary)).toBeInTheDocument()
  expect(screen.getByRole('heading', { level: 2, name: group })).toBeInTheDocument()
  expect(screen.getAllByText(tool).length).toBeGreaterThan(0)
  if (result.failed_cases.length) {
    expect(screen.getByText('Agent-provided failure reason')).toBeInTheDocument()
  }
})

it('keeps localized fixed API errors and Agent answers untouched', async () => {
  state.language = 'zh-CN'
  state.todayError = '请先配置并启用模型连接，再使用 Agent 功能。'
  await i18n.changeLanguage('zh-CN')
  vi.spyOn(api, 'coachAction').mockResolvedValue({
    surface: 'today', action: 'explain_today', answer_markdown: '## Agent output: DO NOT TRANSLATE',
    intent: 'knowledge_qa', trace: {}, sources: [], model: 'test-model', request_id: 'request-1',
  })
  renderRoute('/')

  expect(screen.getByText('请先配置并启用模型连接，再使用 Agent 功能。')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '解释今天' }))
  await waitFor(() => expect(screen.getByText('Agent output: DO NOT TRANSLATE')).toBeInTheDocument())
})
