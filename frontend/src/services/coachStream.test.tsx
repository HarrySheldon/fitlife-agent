import { act, render, renderHook, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { CoachMessages } from '../components/coach/CoachMessages'
import { useCoachController } from '../hooks/useCoach'
import i18n from '../i18n'
import { consumeSseBuffer } from './coachApi'
import type { CoachStreamEvent } from '../types/coach'

beforeEach(async () => {
  sessionStorage.clear()
  await i18n.changeLanguage('en-US')
})

describe('SSE stream parsing and live coach hook rendering', () => {
  it('parses chunked SSE frames, CRLF delimiters, heartbeats, and Last-Event-ID', () => {
    const chunk1 = ': keepalive\r\n\r\nid: 1\r\nevent: turn_status\r\ndata: {"turn_id":"t1","status":"running","stopping":false,"version":2,"stage":"running"}\r\n\r\nid: 2\nevent: answer_delta\n'
    const first = consumeSseBuffer(chunk1)
    expect(first.events).toHaveLength(1)
    expect(first.events[0].event).toBe('turn_status')
    expect(first.lastEventId).toBe(1)

    const chunk2 = `${first.remainder}data: {"turn_id":"t1","message_id":"m1","delta":"Hello","index":0}\n\n`
    const second = consumeSseBuffer(chunk2)
    expect(second.events).toHaveLength(1)
    expect(second.events[0].event).toBe('answer_delta')
    expect(second.events[0].id).toBe(2)
    expect(second.remainder).toBe('')
  })

  it('streams step progress and verified answer deltas into useCoachController', async () => {
    const conv = { conversation_id: 'c1', title: 'Today', created_at: '2026-11-26T00:00:00Z', updated_at: '2026-11-26T00:00:00Z' }
    const runningTurn = { turn_id: 't1', conversation_id: 'c1', status: 'running' as const, stopping: false, receipt: null, error_code: null }
    let emitEvent: ((ev: CoachStreamEvent) => void) | null = null

    const api = {
      list: vi.fn().mockResolvedValue({ conversations: [conv] }),
      create: vi.fn().mockResolvedValue(conv),
      messages: vi.fn().mockResolvedValue({ messages: [] }),
      active: vi.fn().mockResolvedValue({ turn: null }),
      turn: vi.fn().mockResolvedValue({ ...runningTurn, status: 'succeeded' as const }),
      send: vi.fn().mockResolvedValue(runningTurn),
      cancel: vi.fn(),
      remove: vi.fn(),
      rename: vi.fn(),
      streamTurn: vi.fn((_turnId: string, handlers: { onEvent: (ev: CoachStreamEvent) => void }) => {
        emitEvent = handlers.onEvent
        return Promise.resolve()
      }),
    }

    const { result } = renderHook(() => useCoachController('alice', api))
    await waitFor(() => expect(result.current.selected).toBe('c1'))

    await act(async () => {
      await result.current.send({ question: 'Plan chest day', action: 'chat', surface: 'today' })
    })
    expect(api.streamTurn).toHaveBeenCalledWith('t1', expect.objectContaining({ onEvent: expect.any(Function) }))

    act(() => {
      emitEvent?.({
        id: 1,
        event: 'step_progress',
        data: { turn_id: 't1', step: 'knowledge.search', stage: 'knowledge_search', status: 'started', tool_name: 'knowledge.search' },
      })
      emitEvent?.({
        id: 2,
        event: 'answer_delta',
        data: { turn_id: 't1', message_id: 't1-coach', delta: 'Progressive overload ', index: 0 },
      })
      emitEvent?.({
        id: 3,
        event: 'answer_delta',
        data: { turn_id: 't1', message_id: 't1-coach', delta: 'on compound lifts.', index: 1 },
      })
    })

    expect(result.current.streamSteps).toHaveLength(1)
    expect(result.current.streamSteps[0].stage).toBe('knowledge_search')
    expect(result.current.streamingBody).toBe('Progressive overload on compound lifts.')

    const finalMsg = {
      message_id: 't1-coach',
      turn_id: 't1',
      role: 'coach' as const,
      body: 'Progressive overload on compound lifts.',
      created_at: '2026-11-26T00:01:00Z',
    }
    act(() => {
      emitEvent?.({
        id: 4,
        event: 'turn_done',
        data: { turn: { ...runningTurn, status: 'succeeded' }, message: finalMsg },
      })
    })

    expect(result.current.active).toBeNull()
    expect(result.current.streamingBody).toBe('')
    expect(result.current.streamSteps).toEqual([])
    expect(result.current.messages.some(m => m.body === finalMsg.body)).toBe(true)
  })

  it('renders live stream progress stages and verified streaming markdown in CoachMessages', () => {
    render(
      <CoachMessages
        conversation="c1"
        messages={[]}
        streamingActive
        streamSteps={[
          { turn_id: 't1', step: 'knowledge.search', stage: 'knowledge_search', status: 'succeeded', tool_name: 'knowledge.search' },
        ]}
        streamingBody="Verified live reply"
      />,
    )

    expect(screen.getByTestId('coach-stream-progress')).toHaveTextContent('Searching knowledge base')
    expect(screen.getByTestId('coach-streaming-body')).toHaveTextContent('Verified live reply')
  })
})
