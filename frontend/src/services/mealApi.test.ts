import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { MealDraftCreate } from '../types/meals'


const emptyDraft: MealDraftCreate = {
  log_date: '2026-07-24',
  name: 'Lunch',
  meal_type: 'lunch',
  entry_method: 'form',
  items: [],
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

describe('meal API client', () => {
  it('encodes catalog searches and reuses authorization and language headers', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(success([]))
    window.localStorage.setItem('fitlife_access_token', 'meal-token')
    window.localStorage.setItem('fitlife_language', 'zh-CN')
    const { mealApi } = await import('./mealApi')

    await mealApi.searchFoods('米饭 & oats', 12)

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/catalog/foods/search?q=%E7%B1%B3%E9%A5%AD+%26+oats&limit=12',
      expect.objectContaining({ headers: expect.any(Headers) }),
    )
    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers)
    expect(headers.get('Authorization')).toBe('Bearer meal-token')
    expect(headers.get('Accept-Language')).toBe('zh-CN')
  })

  it('sends optimistic-lock and idempotency headers', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(success({ id: 'draft-1', version: 3 }))
      .mockResolvedValueOnce(success({ id: 'meal-1', replayed: false }))
    const { mealApi } = await import('./mealApi')

    await mealApi.updateDraft('draft-1', 2, emptyDraft)
    await mealApi.confirmDraft(
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
})
