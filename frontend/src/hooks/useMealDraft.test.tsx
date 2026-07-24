import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiRequestError } from '../services/api'
import { mealApi } from '../services/mealApi'
import type { MealDraft, MealDraftCreate } from '../types/meals'
import { useMealDraft } from './useMealDraft'


vi.mock('../services/mealApi', () => ({
  mealApi: {
    createDraft: vi.fn(),
    updateDraft: vi.fn(),
    confirmDraft: vi.fn(),
    deleteDraft: vi.fn(),
  },
}))

const initial: MealDraftCreate = {
  log_date: '2026-07-24',
  name: 'Lunch',
  meal_type: 'lunch',
  entry_method: 'form',
  items: [],
}

const remoteDraft: MealDraft = {
  id: 'draft-1',
  user_id: 'user-1',
  payload: {
    ...initial,
    items: [],
  },
  version: 1,
  expires_at: '2026-08-23T00:00:00Z',
  created_at: '2026-07-24T00:00:00Z',
  updated_at: '2026-07-24T00:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useMealDraft', () => {
  it('keeps local values and exposes recovery state after a stale save', async () => {
    vi.mocked(mealApi.createDraft).mockResolvedValue(remoteDraft)
    vi.mocked(mealApi.updateDraft).mockRejectedValue(
      new ApiRequestError(
        'Draft changed in another session.',
        'DRAFT_VERSION_CONFLICT',
        'deterministic',
        409,
      ),
    )
    const { result } = renderHook(() => useMealDraft(initial))

    await act(async () => {
      await result.current.save()
    })
    const changed = { ...initial, name: 'Post-workout meal' }

    await act(async () => {
      result.current.setInput(changed)
    })
    let rejectedMessage = ''
    await act(async () => {
      try {
        await result.current.save()
      } catch (cause) {
        rejectedMessage = (cause as Error).message
      }
    })

    expect(rejectedMessage).toBe('Draft changed in another session.')
    expect(mealApi.updateDraft).toHaveBeenCalledOnce()
    await waitFor(() => expect(result.current.status).toBe('conflict'))
    expect(result.current.input).toEqual(changed)
    expect(result.current.draft?.version).toBe(1)
  })

  it('reuses one confirmation key after a recoverable failure', async () => {
    vi.mocked(mealApi.createDraft).mockResolvedValue(remoteDraft)
    vi.mocked(mealApi.confirmDraft)
      .mockRejectedValueOnce(new Error('network unavailable'))
      .mockResolvedValueOnce({
        id: 'meal-1',
        user_id: 'user-1',
        log_date: initial.log_date,
        name: initial.name,
        meal_type: initial.meal_type,
        position: 1,
        entry_method: 'form',
        items: [],
        created_at: '2026-07-24T00:00:00Z',
        updated_at: '2026-07-24T00:00:00Z',
        replayed: false,
      })
    const uuid = vi.spyOn(globalThis.crypto, 'randomUUID')
      .mockReturnValue('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
    const { result } = renderHook(() => useMealDraft(initial))

    await act(async () => {
      await result.current.save()
    })
    await expect(act(async () => result.current.confirm())).rejects.toThrow(
      'network unavailable',
    )
    await act(async () => {
      await result.current.confirm()
    })

    expect(uuid).toHaveBeenCalledTimes(1)
    expect(vi.mocked(mealApi.confirmDraft).mock.calls[0][2]).toBe(
      vi.mocked(mealApi.confirmDraft).mock.calls[1][2],
    )
  })
})
