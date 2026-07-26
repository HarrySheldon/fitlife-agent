import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { SmartEntryDraftPayload } from '../types/smartEntry'


const payload: SmartEntryDraftPayload = {
  log_date: '2026-07-26',
  raw_text: 'Breakfast: oats 50g',
  parser_version: 'smart-entry-parser-v1',
  candidates: [],
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

describe('smart entry API client', () => {
  it('uses optimistic-lock and idempotency headers for explicit commands', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockImplementation(async () => success({}))
    const { smartEntryApi } = await import('./smartEntryApi')

    await smartEntryApi.updateDraft('draft-1', 2, payload)
    await smartEntryApi.analyzeDraft('draft-1', 3)
    await smartEntryApi.confirmDraft(
      'draft-1',
      4,
      '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
    )

    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get('If-Match'))
      .toBe('2')
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).get('If-Match'))
      .toBe('3')
    const confirmHeaders = new Headers(fetchMock.mock.calls[2][1]?.headers)
    expect(confirmHeaders.get('If-Match')).toBe('4')
    expect(confirmHeaders.get('Idempotency-Key')).toBe(
      '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
    )
  })

  it('finds the latest account-scoped draft by date', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      success(null),
    )
    const { smartEntryApi } = await import('./smartEntryApi')

    await smartEntryApi.findLatestDraft('2026-07-26')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/smart-entry-drafts?date=2026-07-26',
      expect.objectContaining({ headers: expect.any(Headers) }),
    )
  })
})
