import { beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  OverallGoalVersionUpdate,
  ProfileVersionUpdate,
  TargetPreview,
} from '../types'


const setup = {
  profile: null,
  goal: null,
  target: null,
  setup_complete: false,
}

const profileUpdate: ProfileVersionUpdate = {
  age: 30,
  height_cm: 175,
  weight_kg: 70,
  energy_parameter: 'male',
  activity_level: 'moderate',
  auto_target_disabled: false,
  safety_conditions: [],
  effective_from: '2026-07-23T08:00:00Z',
}

const goalUpdate: OverallGoalVersionUpdate = {
  goal: 'fat_loss',
  effective_from: '2026-07-23T08:00:00Z',
}

const preview: TargetPreview = {
  profile_version_id: 'profile-1',
  overall_goal_version_id: 'goal-1',
  targets: { calories: 2172, carbs: 291, protein: 126, fat: 56 },
  source: 'deterministic_calculation',
  formula_version: 'mifflin_st_jeor_v1',
  warnings: [],
  requires_confirmation: false,
  preview_token: 'a'.repeat(64),
}

function success(data: unknown) {
  return new Response(JSON.stringify({ success: true, data, message: '' }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

async function loadApi(apiV1Base?: string) {
  vi.resetModules()
  vi.unstubAllEnvs()
  if (apiV1Base) vi.stubEnv('VITE_API_V1_BASE_URL', apiV1Base)
  return (await import('./api')).api
}

beforeEach(() => {
  window.localStorage.clear()
  vi.restoreAllMocks()
  vi.unstubAllEnvs()
})

describe('profile target API client', () => {
  it('uses the dedicated development base and shared bearer headers', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(success(setup))
    const api = await loadApi()
    window.localStorage.setItem('fitlife_access_token', 'access-token')

    await api.profileSetup()

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/profile',
      expect.objectContaining({ headers: expect.any(Headers) }),
    )
    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers)
    expect(headers.get('Authorization')).toBe('Bearer access-token')
  })

  it('keeps every v1 path intact with an absolute Docker base', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => success(setup))
    const api = await loadApi('http://localhost:8000/api/v1')

    await api.profileSetup()
    await api.saveProfileVersion(profileUpdate)
    await api.overallGoal()
    await api.saveOverallGoal(goalUpdate)
    await api.calculateTargets()
    await api.confirmTargets({
      preview,
      effective_from: '2026-07-23T09:00:00Z',
      acknowledge_warnings: false,
      idempotencyKey: '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
    })
    await api.targetHistory()

    expect(fetchMock.mock.calls.map(([url, init]) => [url, init?.method ?? 'GET'])).toEqual([
      ['http://localhost:8000/api/v1/profile', 'GET'],
      ['http://localhost:8000/api/v1/profile', 'PUT'],
      ['http://localhost:8000/api/v1/goals', 'GET'],
      ['http://localhost:8000/api/v1/goals/overall', 'PUT'],
      ['http://localhost:8000/api/v1/targets/calculate', 'POST'],
      ['http://localhost:8000/api/v1/targets/confirm', 'POST'],
      ['http://localhost:8000/api/v1/targets/history', 'GET'],
    ])
    const confirmInit = fetchMock.mock.calls[5][1]
    const confirmHeaders = new Headers(confirmInit?.headers)
    expect(confirmHeaders.get('If-Match')).toBe(preview.preview_token)
    expect(confirmHeaders.get('Idempotency-Key')).toBe('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
    expect(JSON.parse(String(confirmInit?.body))).toEqual({
      preview,
      effective_from: '2026-07-23T09:00:00Z',
      acknowledge_warnings: false,
    })
  })
})
