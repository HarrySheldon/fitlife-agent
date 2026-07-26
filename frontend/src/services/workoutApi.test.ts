import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { WorkoutDraftCreate } from '../types/workouts'

const emptyDraft: WorkoutDraftCreate = {
  log_date: '2026-07-25',
  title: 'Evening training',
  started_at: null,
  duration_min: null,
  intensity: null,
  entry_method: 'form',
  strength_exercises: [],
  cardio_items: [],
}

function success(data: unknown) {
  return new Response(JSON.stringify({ success: true, data, message: '' }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  vi.resetModules()
  vi.restoreAllMocks()
  window.localStorage.clear()
})

describe('workout API client', () => {
  it('encodes local catalog searches and reuses authorization and language headers', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(success([]))
    window.localStorage.setItem('fitlife_access_token', 'workout-token')
    window.localStorage.setItem('fitlife_language', 'zh-CN')
    const { workoutApi } = await import('./workoutApi')

    await workoutApi.searchExercises('深蹲 & squat', 12)

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/catalog/exercises/search?q=%E6%B7%B1%E8%B9%B2+%26+squat&limit=12',
      expect.objectContaining({ headers: expect.any(Headers) }),
    )
    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers)
    expect(headers.get('Authorization')).toBe('Bearer workout-token')
    expect(headers.get('Accept-Language')).toBe('zh-CN')
  })

  it('sends workout optimistic-lock and UUID idempotency headers', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(success({ id: 'draft-1', version: 3 }))
      .mockResolvedValueOnce(success({ id: 'workout-1', replayed: false }))
    const { workoutApi } = await import('./workoutApi')

    await workoutApi.updateDraft('draft-1', 2, emptyDraft)
    await workoutApi.confirmDraft(
      'draft-1',
      3,
      '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
    )

    const updateHeaders = new Headers(fetchMock.mock.calls[0][1]?.headers)
    expect(updateHeaders.get('If-Match')).toBe('2')
    const confirmHeaders = new Headers(fetchMock.mock.calls[1][1]?.headers)
    expect(confirmHeaders.get('If-Match')).toBe('3')
    expect(confirmHeaders.get('Idempotency-Key')).toBe(
      '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
    )
  })

  it('finds the latest recoverable workout draft by date', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(success(null))
    const { workoutApi } = await import('./workoutApi')

    await workoutApi.findLatestDraft('2026-07-25')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/workout-drafts?date=2026-07-25',
      expect.objectContaining({ headers: expect.any(Headers) }),
    )
  })
})
