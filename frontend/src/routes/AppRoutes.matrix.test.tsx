import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { MemoryRouter, Outlet, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import { api } from '../services/api'
import { mealApi } from '../services/mealApi'
import { smartEntryApi } from '../services/smartEntryApi'
import { workoutApi } from '../services/workoutApi'
import { AppRoutes } from './AppRoutes'

const styles = readFileSync('src/styles/index.css', 'utf8')
const authState = vi.hoisted(() => ({ authenticated: true }))
const profileSetup = {
  setup_complete: true,
  profile: { id: 'profile-1', user_id: 'user-1', age: 30, height_cm: 175, weight_kg: 70, energy_parameter: 'male', activity_level: 'moderate', auto_target_disabled: false, safety_conditions: [], effective_from: '2026-08-26T00:00:00Z', created_at: '2026-08-26T00:00:00Z' },
  goal: { id: 'goal-1', user_id: 'user-1', goal: 'maintenance', effective_from: '2026-08-26T00:00:00Z', created_at: '2026-08-26T00:00:00Z' },
  target: { id: 'target-1', user_id: 'user-1', profile_version_id: 'profile-1', overall_goal_version_id: 'goal-1', calories: 2200, carbs: 250, protein: 140, fat: 70, source: 'manual', formula_version: null, rationale: {}, effective_from: '2026-08-26T00:00:00Z', created_at: '2026-08-26T00:00:00Z' },
}

vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ user: authState.authenticated ? { user_id: 'user-1', display_name: 'Route Matrix' } : null, initializing: false, logout: vi.fn(), replaceSession: vi.fn() }) }))
vi.mock('../hooks/usePreferences', () => ({ usePreferences: () => ({ preferences: { language: 'en-US', unit_system: 'metric', timezone: 'Asia/Shanghai' }, loading: false, error: null, updatePreferences: vi.fn(), localDate: () => '2026-08-26' }) }))
vi.mock('../hooks/useProfileSetup', () => ({ useProfileSetup: () => ({ setup: profileSetup, preview: null, restriction: null, loading: false, saving: false, calculating: false, confirming: false, stalePreview: false, error: null, updateProfile: vi.fn(), updateOverallGoal: vi.fn(), calculateTargets: vi.fn(), confirmTargets: vi.fn() }) }))
vi.mock('../hooks/useProfile', () => ({ useProfile: () => ({ profile: { height_cm: 175, weight_kg: 70, age: 30, gender: 'male', goal: 'maintenance', weekly_training_frequency: 4, diet_preferences: [], allergies_or_restrictions: [], target_weight_kg: 70, daily_calorie_target: 2200, daily_protein_target: 140, experience_level: 'experienced', training_preference: 'mixed', target_mode: 'manual' }, loading: false, saving: false, error: null, save: vi.fn() }) }))
vi.mock('../hooks/useModelSettings', () => ({ useModelSettings: () => ({ settings: { provider: 'openai', protocol: 'responses', base_url: null, model: 'gpt-5.5', enabled: false, api_key_configured: false, api_key_hint: null, test_status: 'untested', test_error_code: null, tested_at: null, updated_at: null, state: 'unconfigured' }, models: [], loading: false, action: null, feedback: null, refresh: vi.fn(), save: vi.fn(), clearApiKey: vi.fn(), listModels: vi.fn(), testConnection: vi.fn() }) }))

vi.mock('../components/Layout', () => ({ Layout: () => <Outlet /> }))
vi.mock('../components/OnboardingGate', () => ({ OnboardingGate: () => <Outlet /> }))
vi.mock('../pages/Auth', async () => {
  const { useLocation } = await import('react-router-dom')
  return { Auth: () => { const location = useLocation(); return <><h1>Login route</h1><output data-testid="login-from">{(location.state as { from?: string } | null)?.from ?? ''}</output></> } }
})
vi.mock('../pages/Today', () => ({ Today: () => <h1>Today route</h1> }))
vi.mock('../pages/Review', () => ({ Review: () => <h1>Review route</h1> }))
vi.mock('../pages/Plan', () => ({ Plan: () => <h1>Plan route</h1> }))
vi.mock('../pages/Profile', () => ({ Profile: () => <h1>Profile route</h1> }))

vi.mock('../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/api')>()
  return { ...original, api: { ...original.api, calendarDays: vi.fn(), calendarDay: vi.fn(), getWeeklyReport: vi.fn(), generateWeeklyReport: vi.fn(), getPlan: vi.fn(), targetHistory: vi.fn() } }
})
vi.mock('../services/mealApi', () => ({ mealApi: { searchFoods: vi.fn(), setFavorite: vi.fn(), createCustomFood: vi.fn(), createDraft: vi.fn(), getDraft: vi.fn(), updateDraft: vi.fn(), deleteDraft: vi.fn(), confirmDraft: vi.fn() } }))
vi.mock('../services/workoutApi', () => ({ workoutApi: { searchExercises: vi.fn(), setFavorite: vi.fn(), createCustomExercise: vi.fn(), createDraft: vi.fn(), findLatestDraft: vi.fn(), getDraft: vi.fn(), updateDraft: vi.fn(), deleteDraft: vi.fn(), confirmDraft: vi.fn() } }))
vi.mock('../services/smartEntryApi', () => ({ smartEntryApi: { createDraft: vi.fn(), findLatestDraft: vi.fn(), getDraft: vi.fn(), updateDraft: vi.fn(), deleteDraft: vi.fn(), analyzeDraft: vi.fn(), confirmDraft: vi.fn() } }))

const taskRoutes = [
  { path: '/today/meal/new?date=2026-08-26', heading: 'Add a meal', back: 'Back to Today', role: 'button', expectedBack: '/' },
  { path: '/today/workout/new?date=2026-08-26', heading: 'Add a workout', back: 'Back to Today', role: 'button', expectedBack: '/' },
  { path: '/today/smart-entry?date=2026-08-26', heading: 'Smart entry', back: 'Back to Today', role: 'button', expectedBack: '/' },
  { path: '/logbook/import', heading: 'CSV import', back: 'Back', role: 'link', expectedBack: '/logbook' },
  { path: '/logbook/2026-08-26', heading: '2026-08-26', back: 'Logbook', role: 'link', expectedBack: '/logbook' },
  { path: '/review/week/2026-W35', heading: '2026-W35', back: 'Back to review', role: 'link', expectedBack: '/review' },
  { path: '/plan/new', heading: 'New plan draft', back: 'Back to plans', role: 'link', expectedBack: '/plan' },
  { path: '/plan/plan-00000001', heading: 'plan-00000001', back: 'Back to plans', role: 'link', expectedBack: '/plan' },
  { path: '/profile/edit', heading: 'Profile', back: 'Back to profile', role: 'link', expectedBack: '/profile' },
  { path: '/settings/general', heading: 'General settings', back: 'Back', role: 'link', expectedBack: '/settings' },
  { path: '/settings/model', heading: 'Model connection', back: 'Back to settings', role: 'link', expectedBack: '/settings' },
  { path: '/settings/security', heading: 'Security', back: 'Back', role: 'link', expectedBack: '/settings' },
  { path: '/settings/security/password', heading: 'Change password', back: 'Back', role: 'link', expectedBack: '/settings/security' },
  { path: '/settings/security/sessions', heading: 'Other sessions', back: 'Back', role: 'link', expectedBack: '/settings/security' },
  { path: '/settings/privacy', heading: 'Privacy and data', back: 'Back', role: 'link', expectedBack: '/settings' },
  { path: '/settings/privacy/delete', heading: 'Delete account', back: 'Back', role: 'link', expectedBack: '/settings/privacy' },
] as const

const protectedRoutes = ['/', '/today/meal/new', '/today/workout/new', '/today/smart-entry', '/logbook', '/logbook/import', '/logbook/2026-08-26', '/review', '/review/week/2026-W35', '/plan', '/plan/new', '/plan/plan-00000001', '/profile', '/profile/edit', '/settings', '/settings/general', '/settings/model', '/settings/security', '/settings/security/password', '/settings/security/sessions', '/settings/privacy', '/settings/privacy/delete', '/evaluation'] as const

function LocationProbe() { return <output data-testid="location">{useLocation().pathname}</output> }
function renderRoute(path: string) { return render(<MemoryRouter initialEntries={[path]}><AppRoutes /><LocationProbe /></MemoryRouter>) }

beforeEach(async () => {
  authState.authenticated = true
  localStorage.clear()
  vi.clearAllMocks()
  vi.mocked(api.calendarDays).mockResolvedValue([])
  vi.mocked(api.calendarDay).mockResolvedValue({ summary: { date: '2026-08-26', calories: 0, protein: 0, carbs: 0, fat: 0, meal_count: 0, training_sessions: 0, training_duration_min: 0, has_data: false }, meals: [], workouts: [] })
  vi.mocked(api.getWeeklyReport).mockResolvedValue(null as never)
  vi.mocked(api.getPlan).mockResolvedValue(null as never)
  vi.mocked(api.targetHistory).mockResolvedValue([])
  vi.mocked(mealApi.searchFoods).mockResolvedValue([])
  vi.mocked(workoutApi.searchExercises).mockResolvedValue([])
  vi.mocked(workoutApi.findLatestDraft).mockResolvedValue(null)
  vi.mocked(smartEntryApi.findLatestDraft).mockResolvedValue(null)
  await i18n.changeLanguage('en-US')
})

describe('settings and product task route matrix', () => {
  it.each(taskRoutes)('renders the real $path page shell and returns to $expectedBack', async ({ path, heading, back, role, expectedBack }) => {
    renderRoute(path)
    expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeInTheDocument()
    fireEvent.click(screen.getByRole(role, { name: new RegExp(`${back}$`) }))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(new RegExp(`^${expectedBack}$`)))
  })

  it.each(protectedRoutes)('protects %s and preserves the attempted pathname', async (path) => {
    authState.authenticated = false
    renderRoute(path)
    expect(await screen.findByRole('heading', { name: 'Login route' })).toBeInTheDocument()
    expect(screen.getByTestId('login-from')).toHaveTextContent(path)
  })

  it.each(['en-US', 'zh-CN'] as const)('renders real long-form copy at a 390px viewport in %s across every route family', async (language) => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    await i18n.changeLanguage(language)
    for (const path of ['/today/smart-entry?date=2026-08-26', '/logbook/2026-08-26', '/review/week/2026-W35', '/plan/plan-00000001', '/profile/edit', '/settings/model']) {
      const view = renderRoute(path)
      expect(await screen.findByRole('heading', { level: 1 })).toBeInTheDocument()
      expect(view.container.querySelector('.page-stack')).toBeInTheDocument()
      expect(view.container.querySelector('[style*="min-width"], [style*="white-space"]')).not.toBeInTheDocument()
      view.unmount()
    }
  })

  it('defines shrink, wrap, and single-column mobile constraints for every route family', () => {
    for (const rule of [
      /\.settings-row-copy\s*{[^}]*min-width:\s*0/s,
      /\.settings-row-copy strong,\s*\.settings-row-copy span\s*{[^}]*overflow-wrap:\s*anywhere/s,
      /@media \(max-width:\s*720px\)[\s\S]*?\.settings-task-header\s*{[^}]*minmax\(0, 1fr\)/,
      /@media \(max-width:\s*620px\)[\s\S]*?\.meal-entry-header\s*{[^}]*minmax\(0, 1fr\)/,
      /@media \(max-width:\s*620px\)[\s\S]*?\.smart-entry-header\s*{[^}]*minmax\(0, 1fr\)/,
      /@media \(max-width:\s*900px\)[\s\S]*?\.daily-log-grid[\s\S]*?grid-template-columns:\s*1fr/,
      /@media \(max-width:\s*900px\)[\s\S]*?\.review-layout,[\s\S]*?\.plan-layout,[\s\S]*?\.profile-layout[\s\S]*?grid-template-columns:\s*1fr/,
      /@media \(max-width:\s*620px\)[\s\S]*?\.profile-field-grid[\s\S]*?grid-template-columns:\s*1fr/,
      /\.exercise-result-main strong,[\s\S]*?overflow-wrap:\s*anywhere/,
    ]) expect(styles).toMatch(rule)
  })
})
