import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { smartEntryApi } from '../services/smartEntryApi'
import type {
  SmartEntryDraft,
  SmartEntryDraftPayload,
} from '../types/smartEntry'
import { useSmartEntryDraft } from './useSmartEntryDraft'
import { clearSmartEntryRecovery } from '../services/smartEntryRecovery'


vi.mock('../services/smartEntryApi', () => ({
  smartEntryApi: {
    createDraft: vi.fn(),
    findLatestDraft: vi.fn(),
    getDraft: vi.fn(),
    updateDraft: vi.fn(),
    deleteDraft: vi.fn(),
    analyzeDraft: vi.fn(),
    confirmDraft: vi.fn(),
    startInteraction: vi.fn(), answerInteraction: vi.fn(), correctInteraction: vi.fn(), confirmItems: vi.fn(),
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
  vi.restoreAllMocks()
  Object.values(smartEntryApi).forEach((method) => vi.mocked(method).mockReset())
  globalThis.localStorage.clear()
  vi.mocked(smartEntryApi.findLatestDraft).mockResolvedValue(null)
  vi.mocked(smartEntryApi.createDraft).mockResolvedValue(draft)
  vi.mocked(smartEntryApi.updateDraft).mockResolvedValue({
    ...draft,
    version: 2,
  })
})

describe('useSmartEntryDraft', () => {
  it.each(['analyze', 'confirm'] as const)('does not start %s after logout between saving and the next command', async (command) => {
    const key = 'fitlife:smart-entry:user-1:2026-07-26'
    vi.mocked(smartEntryApi.updateDraft).mockImplementation(() => {
      // The third microtask runs after the save's guarded completion, before its caller resumes.
      queueMicrotask(() => queueMicrotask(() => queueMicrotask(() => clearSmartEntryRecovery('user-1'))))
      return Promise.resolve({ ...draft, version: 2 })
    })
    vi.mocked(smartEntryApi.analyzeDraft).mockResolvedValue({ ...draft, version: 3 })
    vi.mocked(smartEntryApi.confirmDraft).mockResolvedValue({ draft_id: draft.id, log_date: payload.log_date, meal_ids: [], training_session_id: null, replayed: false })
    const { result } = renderHook(() => useSmartEntryDraft(key))
    await act(async () => { await result.current.parse({ log_date: payload.log_date, raw_text: payload.raw_text }) })
    await act(async () => { await result.current[command](payload).catch(() => {}) })
    expect(smartEntryApi.updateDraft).toHaveBeenCalledOnce()
    expect(smartEntryApi.analyzeDraft).not.toHaveBeenCalled()
    expect(smartEntryApi.confirmDraft).not.toHaveBeenCalled()
    expect(localStorage.getItem(key)).toBeNull()
    expect(result.current.draft).toBeNull()
  })

  it('does not turn a successful server confirmation into failure when storage is blocked', async () => {
    const saved = { draft_id: draft.id, log_date: payload.log_date, meal_ids: ['meal-1'], training_session_id: null, replayed: false }
    vi.mocked(smartEntryApi.confirmDraft).mockResolvedValue(saved)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage blocked') })
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('storage blocked') })
    const { result } = renderHook(() => useSmartEntryDraft('recovery-key'))
    await act(async () => { await result.current.parse({ log_date: payload.log_date, raw_text: payload.raw_text }) })
    await act(async () => { expect(await result.current.confirm(payload)).toEqual(saved) })
    expect(result.current.status).toBe('idle')
    expect(result.current.confirmed).toEqual(saved)
  })

  it('fetches latest state after a conflict without replaying the failed mutation', async () => {
    vi.mocked(smartEntryApi.confirmDraft).mockRejectedValue(Object.assign(new Error('version conflict'), { status: 409 }))
    vi.mocked(smartEntryApi.getDraft).mockResolvedValue({ ...draft, version: 5 })
    const { result } = renderHook(() => useSmartEntryDraft('fitlife:smart-entry:user-1:2026-07-26'))
    await act(async () => { await result.current.parse({ log_date: payload.log_date, raw_text: payload.raw_text }) })
    await act(async () => {
      await expect(result.current.confirm(payload)).rejects.toThrow('version conflict')
    })
    expect(result.current.status).toBe('conflict')
    expect(result.current.draft?.version).toBe(5)
    expect(smartEntryApi.confirmDraft).toHaveBeenCalledTimes(1)
    expect(smartEntryApi.getDraft).toHaveBeenCalledWith('draft-1')
  })

  it('does not recover a deleted task from a cached health body or post on 404', async () => {
    localStorage.setItem('recovery-key', JSON.stringify({ draft, idempotencyKey: 'old', fingerprint: JSON.stringify(payload) }))
    vi.mocked(smartEntryApi.getDraft).mockRejectedValue(Object.assign(new Error('task unavailable'), { status: 404 }))
    const { result } = renderHook(() => useSmartEntryDraft('recovery-key'))
    await expect(act(async () => result.current.restore(payload.log_date))).rejects.toThrow('task unavailable')
    expect(result.current.draft).toBeNull()
    expect(localStorage.getItem('recovery-key')).toBeNull()
    expect(smartEntryApi.confirmDraft).not.toHaveBeenCalled()
    expect(smartEntryApi.createDraft).not.toHaveBeenCalled()
  })

  it('ignores a previous owner’s late restore after switching users', async () => {
    let resolve!: (value: SmartEntryDraft) => void
    vi.mocked(smartEntryApi.findLatestDraft).mockReturnValueOnce(new Promise((done) => { resolve = done }))
    const { result, rerender } = renderHook(({ owner }) => useSmartEntryDraft(`fitlife:smart-entry:${owner}:2026-07-26`), { initialProps: { owner: 'user-1' } })
    let restoring!: Promise<unknown>
    act(() => { restoring = result.current.restore(payload.log_date).catch(() => {}) })
    rerender({ owner: 'user-2' })
    expect(result.current.draft).toBeNull()
    await act(async () => { resolve(draft); await restoring })
    expect(result.current.draft).toBeNull()
  })

  it('does not post a confirmation when logout occurs during fingerprint computation', async () => {
    const key = 'fitlife:smart-entry:user-1:2026-07-26'
    const { result } = renderHook(() => useSmartEntryDraft(key))
    await act(async () => { await result.current.parse({ log_date: payload.log_date, raw_text: payload.raw_text }) })
    let resolve!: (value: ArrayBuffer) => void
    vi.spyOn(crypto.subtle, 'digest').mockImplementationOnce(() => new Promise((done) => { resolve = done }))
    let confirming!: Promise<unknown>
    act(() => { confirming = result.current.confirm(payload).catch(() => {}) })
    act(() => clearSmartEntryRecovery('user-1'))
    await act(async () => { resolve(new ArrayBuffer(32)); await confirming })
    expect(smartEntryApi.confirmDraft).not.toHaveBeenCalled()
    expect(smartEntryApi.updateDraft).not.toHaveBeenCalled()
    expect(localStorage.getItem(key)).toBeNull()
    expect(result.current.draft).toBeNull()
  })

  it('clears only the logging-out owner’s references and ignores late confirmation completion', async () => {
    const key = 'fitlife:smart-entry:user-1:2026-07-26'
    let resolve!: (value: Awaited<ReturnType<typeof smartEntryApi.confirmDraft>>) => void
    vi.mocked(smartEntryApi.confirmDraft).mockReturnValue(new Promise((done) => { resolve = done }))
    localStorage.setItem('fitlife:smart-entry:user-2:2026-07-26', 'other-owner')
    const { result } = renderHook(() => useSmartEntryDraft(key))
    await act(async () => { await result.current.parse({ log_date: payload.log_date, raw_text: payload.raw_text }) })
    let confirming!: Promise<unknown>
    await act(async () => { confirming = result.current.confirm(payload).catch(() => {}); await new Promise((done) => setTimeout(done, 0)) })
    act(() => clearSmartEntryRecovery('user-1'))
    await act(async () => {
      resolve({ draft_id: draft.id, log_date: payload.log_date, meal_ids: [], training_session_id: null, replayed: false })
      await confirming
    })
    expect(localStorage.getItem(key)).toBeNull()
    expect(localStorage.getItem('fitlife:smart-entry:user-2:2026-07-26')).toBe('other-owner')
    expect(result.current.confirmed).toBeNull()
    expect(result.current.draft).toBeNull()
  })

  it('rejects a server draft belonging to another account', async () => {
    vi.mocked(smartEntryApi.findLatestDraft).mockResolvedValue({ ...draft, user_id: 'user-2' })
    const { result } = renderHook(() => useSmartEntryDraft('fitlife:smart-entry:user-1:2026-07-26'))
    await expect(act(async () => result.current.restore(payload.log_date))).rejects.toThrow('SMART_ENTRY_OWNER_MISMATCH')
    expect(result.current.draft).toBeNull()
  })

  it('persists only an opaque reference and restores the server draft without posting', async () => {
    vi.mocked(smartEntryApi.confirmDraft).mockRejectedValue(new Error('response lost'))
    vi.mocked(smartEntryApi.getDraft).mockResolvedValue({ ...draft, version: 2 })
    const first = renderHook(() => useSmartEntryDraft('smart-entry:user-1:2026-07-26'))
    await act(async () => {
      await first.result.current.parse({ log_date: payload.log_date, raw_text: payload.raw_text })
    })
    await expect(act(async () => first.result.current.confirm(payload))).rejects.toThrow('response lost')
    const persisted = globalThis.localStorage.getItem('smart-entry:user-1:2026-07-26')!
    expect(persisted).not.toContain(payload.raw_text)
    expect(persisted).not.toContain('candidates')
    expect(persisted).not.toContain('version')
    expect(JSON.parse(persisted)).toEqual({
      taskId: 'draft-1',
      idempotencyKey: expect.any(String),
      fingerprint: expect.stringMatching(/^[a-f0-9]{64}$/),
    })
    first.unmount()
    vi.mocked(smartEntryApi.confirmDraft).mockClear()
    const restored = renderHook(() => useSmartEntryDraft('smart-entry:user-1:2026-07-26'))
    await act(async () => { await restored.result.current.restore(payload.log_date) })
    expect(smartEntryApi.getDraft).toHaveBeenCalledWith('draft-1')
    expect(restored.result.current.draft).toEqual({ ...draft, version: 2 })
    expect(smartEntryApi.confirmDraft).not.toHaveBeenCalled()
  })

  it('sanitizes legacy cached health content and fetches by reference', async () => {
    globalThis.localStorage.setItem('recovery-key', JSON.stringify({
      draft, idempotencyKey: 'legacy-key', fingerprint: JSON.stringify(payload),
    }))
    vi.mocked(smartEntryApi.getDraft).mockResolvedValue({ ...draft, version: 4 })
    const { result } = renderHook(() => useSmartEntryDraft('recovery-key'))
    await act(async () => { await result.current.restore(payload.log_date) })
    expect(smartEntryApi.getDraft).toHaveBeenCalledWith('draft-1')
    expect(result.current.draft?.version).toBe(4)
    expect(globalThis.localStorage.getItem('recovery-key')).toBeNull()
    expect(smartEntryApi.confirmDraft).not.toHaveBeenCalled()
  })

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
    vi.mocked(smartEntryApi.getDraft).mockResolvedValue({ ...draft, version: 2 })
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
