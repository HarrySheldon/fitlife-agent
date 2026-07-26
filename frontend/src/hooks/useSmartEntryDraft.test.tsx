import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { smartEntryApi } from '../services/smartEntryApi'
import type {
  SmartEntryDraft,
  SmartEntryDraftPayload,
} from '../types/smartEntry'
import { useSmartEntryDraft } from './useSmartEntryDraft'


vi.mock('../services/smartEntryApi', () => ({
  smartEntryApi: {
    createDraft: vi.fn(),
    findLatestDraft: vi.fn(),
    getDraft: vi.fn(),
    updateDraft: vi.fn(),
    deleteDraft: vi.fn(),
    analyzeDraft: vi.fn(),
    confirmDraft: vi.fn(),
  },
}))

const payload: SmartEntryDraftPayload = {
  log_date: '2026-07-26',
  raw_text: 'Breakfast: oats 50g',
  parser_version: 'smart-entry-parser-v1',
  candidates: [],
}

const draft: SmartEntryDraft = {
  id: 'draft-1',
  user_id: 'user-1',
  payload,
  version: 1,
  agent_status: 'not_requested',
  agent_prompt_version: null,
  agent_model: null,
  agent_metadata: {},
  expires_at: '2026-08-25T00:00:00Z',
  created_at: '2026-07-26T00:00:00Z',
  updated_at: '2026-07-26T00:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
  globalThis.localStorage.clear()
  vi.mocked(smartEntryApi.findLatestDraft).mockResolvedValue(null)
  vi.mocked(smartEntryApi.createDraft).mockResolvedValue(draft)
  vi.mocked(smartEntryApi.updateDraft).mockResolvedValue({
    ...draft,
    version: 2,
  })
})

describe('useSmartEntryDraft', () => {
  it('never analyzes until the explicit analyze command', async () => {
    vi.mocked(smartEntryApi.analyzeDraft).mockResolvedValue({
      ...draft,
      version: 3,
      agent_status: 'completed',
    })
    const { result } = renderHook(() => useSmartEntryDraft('recovery-key'))

    await act(async () => {
      await result.current.parse({
        log_date: payload.log_date,
        raw_text: payload.raw_text,
      })
    })
    expect(smartEntryApi.analyzeDraft).not.toHaveBeenCalled()

    await act(async () => {
      await result.current.analyze(payload)
    })
    expect(smartEntryApi.analyzeDraft).toHaveBeenCalledWith('draft-1', 2)
  })

  it('reuses a persisted confirmation after a lost response and refresh', async () => {
    vi.mocked(smartEntryApi.confirmDraft)
      .mockRejectedValueOnce(new Error('response lost'))
      .mockResolvedValueOnce({
        draft_id: 'draft-1',
        log_date: payload.log_date,
        meal_ids: ['meal-1'],
        training_session_id: null,
        replayed: true,
      })
    vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue(
      '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
    )
    const first = renderHook(() => useSmartEntryDraft('recovery-key'))
    await act(async () => {
      await first.result.current.parse({
        log_date: payload.log_date,
        raw_text: payload.raw_text,
      })
    })
    await expect(act(async () => first.result.current.confirm(payload)))
      .rejects.toThrow('response lost')
    first.unmount()

    const restored = renderHook(() => useSmartEntryDraft('recovery-key'))
    await act(async () => {
      await restored.result.current.restore(payload.log_date)
    })
    await act(async () => {
      await restored.result.current.confirm(payload)
    })

    expect(smartEntryApi.updateDraft).toHaveBeenCalledTimes(1)
    expect(smartEntryApi.confirmDraft).toHaveBeenCalledTimes(2)
    expect(smartEntryApi.confirmDraft).toHaveBeenLastCalledWith(
      'draft-1',
      2,
      '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
    )
    expect(globalThis.localStorage.getItem('recovery-key')).toBeNull()
  })
})
