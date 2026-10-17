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
  it('sends revision-bound selections, answer nulls, and only correction fields', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => success({}))
    const { smartEntryApi } = await import('./smartEntryApi')
    await smartEntryApi.answerInteraction('draft/1', 4, 'key-a', 'group-2', [{ item_id: 'food-1', field: 'amount', value: null }])
    await smartEntryApi.correctInteraction('draft/1', 5, 'key-b', 'food-1', 2, { amount: 100, intake_ratio: 0.5, interaction: { active: true } } as Parameters<typeof smartEntryApi.correctInteraction>[5])
    await smartEntryApi.confirmItems('draft/1', 6, 'key-c', [{ item_id: 'food-1', item_revision: 3 }], [{ item_id: 'food-1', item_revision: 3 }])
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/smart-entry-drafts/draft%2F1/interaction/answers')
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ expected_version: 4, question_group_id: 'group-2', answers: [{ item_id: 'food-1', field: 'amount', value: null }] })
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({ expected_version: 5, item_id: 'food-1', item_revision: 2, updates: { amount: 100, intake_ratio: 0.5 } })
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({ expected_version: 6, selections: [{ item_id: 'food-1', item_revision: 3 }], accepted_estimates: [{ item_id: 'food-1', item_revision: 3 }] })
    expect(new Headers(fetchMock.mock.calls[2][1]?.headers).get('Idempotency-Key')).toBe('key-c')
  })

  it('reads server capabilities and posts only whitelisted interaction command fields', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => success({}))
    const { smartEntryApi } = await import('./smartEntryApi')
    await smartEntryApi.capabilities()
    await smartEntryApi.startInteraction('draft-1', 2, 'command-key')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/smart-entry-drafts/capabilities')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/smart-entry-drafts/draft-1/interaction/start')
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({ expected_version: 2 })
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).get('Idempotency-Key')).toBe('command-key')
    await smartEntryApi.updateDraft('draft-1', 2, {
      ...payload,
      interaction: { active: true },
    } as SmartEntryDraftPayload)
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual(payload)
  })

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
