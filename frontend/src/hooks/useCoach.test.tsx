import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useCoachController } from './useCoach'
beforeEach(() => sessionStorage.clear())

const conversation = { conversation_id: 'c1', title: 'Today', created_at: '2026-10-19T00:00:00Z', updated_at: '2026-10-19T00:00:00Z' }
const turn = { turn_id: 't1', conversation_id: 'c1', status: 'running' as const, stopping: false, receipt: null, error_code: null }
function fakeApi() {
  return { list: vi.fn().mockResolvedValue({ conversations: [conversation] }), create: vi.fn().mockResolvedValue(conversation),
    messages: vi.fn().mockResolvedValue({ messages: [] }), active: vi.fn().mockResolvedValue({ turn: null }),
    turn: vi.fn().mockResolvedValue({ ...turn, status: 'succeeded' }), send: vi.fn().mockResolvedValue(turn),
    cancel: vi.fn().mockResolvedValue({ ...turn, stopping: true, notice: 'Charges may apply.' }),
    remove: vi.fn().mockResolvedValue({ deleted: true }), rename: vi.fn().mockResolvedValue(conversation) }
}

it('opening, minimizing and maximizing never send a model request', async () => {
  const api = fakeApi()
  const { result } = renderHook(() => useCoachController('alice', api))
  await waitFor(() => expect(result.current.selected).toBe('c1'))
  act(() => { result.current.show(); result.current.setOpen(false); result.current.setMaximized(true); result.current.show() })
  expect(api.send).not.toHaveBeenCalled()
  expect(api.create).not.toHaveBeenCalled()
})

it('keeps drafts isolated by chat and preserves them when minimized', async () => {
  const { result } = renderHook(() => useCoachController('alice', fakeApiStable))
  await waitFor(() => expect(result.current.selected).toBe('c1'))
  act(() => result.current.setDraft('private first'))
  act(() => result.current.newChat())
  expect(result.current.draft).toBe('')
  act(() => result.current.setDraft('private second'))
  act(() => result.current.setSelected('c1'))
  expect(result.current.draft).toBe('private first')
  act(() => result.current.setOpen(false))
  expect(result.current.draft).toBe('private first')
})
const fakeApiStable = fakeApi()

it('keeps the selected chat failure when another chat finishes in the background', async () => {
  const api = fakeApi()
  const failed = { ...turn, turn_id: 'failed-b', conversation_id: 'c2', status: 'failed' as const }
  api.list.mockResolvedValue({ conversations: [conversation, { ...conversation, conversation_id: 'c2' }] })
  api.messages.mockImplementation(async (id: string) => ({ messages: id === 'c2'
    ? [{ message_id: 'mb', turn_id: 'failed-b', role: 'user', body: 'Explain protein', created_at: conversation.created_at }] : [] }))
  api.turn.mockImplementation(async (id: string) => id === 'failed-b' ? failed : { ...turn, status: 'succeeded' as const })
  const { result } = renderHook(() => useCoachController('alice', api))
  await waitFor(() => expect(result.current.selected).toBe('c1'))
  await act(async () => result.current.send({ question: 'Today?', action: 'chat', surface: 'today' }))
  act(() => result.current.setSelected('c2'))
  await waitFor(() => expect(result.current.lastTurn?.turn_id).toBe('failed-b'))
  await waitFor(() => expect(api.turn).toHaveBeenCalledWith('t1'), { timeout: 4000 })
  expect(result.current.lastTurn?.status).toBe('failed')
  expect(result.current.selected).toBe('c2')
})

it('recovers the selected identifier without persisting or resending chat text', async () => {
  const api = fakeApi()
  sessionStorage.setItem('fitlife-coach-selected:alice', 'c2')
  api.list.mockResolvedValue({ conversations: [conversation, { ...conversation, conversation_id: 'c2' }] })
  const { result } = renderHook(() => useCoachController('alice', api))
  await waitFor(() => expect(result.current.selected).toBe('c2'))
  act(() => result.current.setDraft('private draft'))
  expect(JSON.stringify(sessionStorage)).not.toContain('private draft')
  expect(api.send).not.toHaveBeenCalled()
})

it('double clicks create only one submission and use an explicit idempotency key', async () => {
  const api = fakeApi()
  const { result } = renderHook(() => useCoachController('alice', api))
  await waitFor(() => expect(result.current.selected).toBe('c1'))
  await act(async () => {
    await Promise.all([result.current.send({ question: 'Today?', action: 'chat', surface: 'today' }), result.current.send({ question: 'Today?', action: 'chat', surface: 'today' })])
  })
  expect(api.send).toHaveBeenCalledTimes(1)
  expect(api.send.mock.calls[0][2]).toEqual(expect.any(String))
  act(() => result.current.setOpen(false))
  expect(api.cancel).not.toHaveBeenCalled()
  expect(result.current.active?.turn_id).toBe('t1')
})

it('a failed submission is not silently retried and retains the draft', async () => {
  const api = fakeApi()
  api.send.mockRejectedValue(new Error('unknown POST outcome'))
  const { result } = renderHook(() => useCoachController('alice', api))
  await waitFor(() => expect(result.current.selected).toBe('c1'))
  act(() => result.current.setDraft('keep me'))
  await act(async () => result.current.send({ question: 'keep me', action: 'chat', surface: 'today' }))
  expect(api.send).toHaveBeenCalledTimes(1)
  expect(result.current.draft).toBe('keep me')
  expect(result.current.error).toBe(true)
})

it('clears the submitted draft in the newly created chat, not just the empty slot', async () => {
  const api = fakeApi()
  api.list.mockResolvedValue({ conversations: [] })
  const { result } = renderHook(() => useCoachController('alice', api))
  await waitFor(() => expect(api.list).toHaveBeenCalled())
  act(() => result.current.setDraft('First question'))
  await act(async () => result.current.send({ question: 'First question', action: 'chat', surface: 'today' }))
  expect(result.current.selected).toBe('c1')
  expect(result.current.draft).toBe('')
})

it('tracks an accepted turn recovered after a lost POST response and reads its final answer', async () => {
  const api = fakeApi()
  api.active.mockResolvedValueOnce({ turn: null }).mockResolvedValueOnce({ turn }).mockResolvedValue({ turn: null })
  api.send.mockRejectedValue(new Error('response lost'))
  const { result } = renderHook(() => useCoachController('alice', api))
  await waitFor(() => expect(result.current.selected).toBe('c1'))
  await act(async () => result.current.send({ question: 'Today?', action: 'chat', surface: 'today' }))
  expect(result.current.active?.turn_id).toBe('t1')
  await waitFor(() => expect(result.current.lastTurn?.status).toBe('succeeded'), { timeout: 4000 })
  expect(api.send).toHaveBeenCalledTimes(1)
  expect(api.turn).toHaveBeenCalledWith('t1')
})

it('reads the transcript even if a lost POST completed before recovery found an active turn', async () => {
  const api = fakeApi()
  const { result } = renderHook(() => useCoachController('alice', api))
  await waitFor(() => expect(result.current.selected).toBe('c1'))
  api.send.mockRejectedValue(new Error('response lost'))
  api.messages.mockResolvedValue({ messages: [{ message_id: 'm1', turn_id: 't1', role: 'coach', body: 'Already completed', created_at: '2026-10-19T00:00:00Z' }] })
  await act(async () => result.current.send({ question: 'Today?', action: 'chat', surface: 'today' }))
  expect(result.current.messages[0].body).toBe('Already completed')
  expect(api.send).toHaveBeenCalledTimes(1)
})

it('a failed stale completion read cannot erase a newer turn tracker', async () => {
  const api = fakeApi()
  const oldTurn = { ...turn, turn_id: 'old-turn' }
  api.active.mockResolvedValueOnce({ turn: oldTurn }).mockResolvedValue({ turn: null })
  let rejectOld: (reason: Error) => void = () => {}
  api.turn.mockImplementation(id => id === 'old-turn'
    ? new Promise((_, reject) => { rejectOld = reject })
    : Promise.resolve({ ...turn, status: 'succeeded' }))
  const { result } = renderHook(() => useCoachController('alice', api))
  await waitFor(() => expect(api.turn).toHaveBeenCalledWith('old-turn'), { timeout: 2500 })
  await act(async () => result.current.send({ question: 'New question', action: 'chat', surface: 'today' }))
  await act(async () => { rejectOld(new Error('old chat was deleted')) })
  await waitFor(() => expect(api.turn).toHaveBeenCalledWith('t1'), { timeout: 2500 })
  expect(result.current.lastTurn?.status).toBe('succeeded')
})

it('does not carry a stop notice into the next turn or another chat', async () => {
  const api = fakeApi()
  api.cancel.mockResolvedValue({ ...turn, status: 'cancelled', stopping: false, notice: 'Charges may apply.' })
  const { result } = renderHook(() => useCoachController('alice', api))
  await waitFor(() => expect(result.current.selected).toBe('c1'))

  await act(async () => result.current.send({ question: 'First', action: 'chat', surface: 'today' }))
  await waitFor(() => expect(result.current.active?.turn_id).toBe('t1'))
  await act(async () => result.current.stop())
  expect(result.current.notice).toBe('Charges may apply.')

  await act(async () => result.current.send({ question: 'Second', action: 'chat', surface: 'today' }))
  expect(result.current.notice).toBe('')

  await act(async () => result.current.stop())
  expect(result.current.notice).toBe('Charges may apply.')
  act(() => result.current.newChat())
  expect(result.current.notice).toBe('')
})
