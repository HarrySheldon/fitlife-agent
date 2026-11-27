import { API_V1_BASE, requestHeaders, requestV1 } from './api'
import type {
  CoachConversation,
  CoachMessage,
  CoachSend,
  CoachStreamEvent,
  CoachTurn,
} from '../types/coach'

const id = encodeURIComponent

export interface SseParseResult {
  events: CoachStreamEvent[]
  remainder: string
  lastEventId: number | null
}

/**
 * Consume incoming SSE text chunk(s) and return complete frames + trailing buffer.
 * Handles CRLF line endings, heartbeats (`: keepalive`), multi-line `data:`, and `id:`.
 */
export function consumeSseBuffer(buffer: string): SseParseResult {
  const normalized = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
  const frames = normalized.split('\n\n')
  const remainder = frames.pop() ?? ''
  const events: CoachStreamEvent[] = []
  let lastEventId: number | null = null

  for (const frame of frames) {
    if (!frame.trim()) continue
    let rawId = 0
    let eventName = ''
    const dataLines: string[] = []
    for (const line of frame.split('\n')) {
      if (!line || line.startsWith(':')) continue
      const colon = line.indexOf(':')
      const field = colon === -1 ? line : line.slice(0, colon)
      let value = colon === -1 ? '' : line.slice(colon + 1)
      if (value.startsWith(' ')) value = value.slice(1)
      if (field === 'id') {
        const parsed = Number.parseInt(value, 10)
        if (!Number.isNaN(parsed)) {
          rawId = parsed
          lastEventId = parsed
        }
      } else if (field === 'event') {
        eventName = value
      } else if (field === 'data') {
        dataLines.push(value)
      }
    }
    if (!eventName || dataLines.length === 0) continue
    try {
      const parsedData = JSON.parse(dataLines.join('\n'))
      events.push({ id: rawId, event: eventName, data: parsedData } as CoachStreamEvent)
    } catch {
      // Ignore malformed SSE payload frames instead of terminating stream reader.
    }
  }
  return { events, remainder, lastEventId }
}

export interface StreamTurnHandlers {
  onEvent: (event: CoachStreamEvent) => void
  onError?: (error: unknown) => void
  onClose?: () => void
  signal?: AbortSignal
  afterId?: number
}

export const coachApi = {
  list: () => requestV1<{ conversations: CoachConversation[] }>('/coach/conversations'),
  create: (title?: string) => requestV1<CoachConversation>('/coach/conversations', { method: 'POST', body: JSON.stringify({ title }) }),
  rename: (conversation: string, title: string) => requestV1<CoachConversation>(`/coach/conversations/${id(conversation)}`, { method: 'PATCH', body: JSON.stringify({ title }) }),
  remove: (conversation: string) => requestV1<{ deleted: boolean }>(`/coach/conversations/${id(conversation)}`, { method: 'DELETE' }),
  messages: (conversation: string) => requestV1<{ messages: CoachMessage[] }>(`/coach/conversations/${id(conversation)}/messages`),
  active: () => requestV1<{ turn: CoachTurn | null; capabilities?: { explicit_read_scope: boolean } }>('/coach/active-turn'),
  turn: (turn: string) => requestV1<CoachTurn>(`/coach/turns/${id(turn)}`),
  send: (conversation: string, payload: CoachSend, key: string) => requestV1<CoachTurn>(`/coach/conversations/${id(conversation)}/turns`, {
    method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(payload),
  }),
  cancel: (turn: string) => requestV1<CoachTurn & { notice: string }>(`/coach/turns/${id(turn)}/cancel`, { method: 'POST' }),
  async streamTurn(turnId: string, handlers: StreamTurnHandlers): Promise<void> {
    const headers = requestHeaders({
      headers: {
        Accept: 'text/event-stream',
        ...(typeof handlers.afterId === 'number' && handlers.afterId > 0
          ? { 'Last-Event-ID': String(handlers.afterId) }
          : {}),
      },
    })
    const query = typeof handlers.afterId === 'number' && handlers.afterId > 0
      ? `?after_id=${encodeURIComponent(String(handlers.afterId))}`
      : ''
    try {
      const response = await fetch(`${API_V1_BASE}/coach/turns/${id(turnId)}/stream${query}`, {
        method: 'GET',
        headers,
        signal: handlers.signal,
      })
      if (!response.ok || !response.body) {
        throw new Error(`SSE_${response.status}`)
      }
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parsed = consumeSseBuffer(buffer)
        buffer = parsed.remainder
        for (const ev of parsed.events) {
          handlers.onEvent(ev)
        }
      }
      if (buffer.trim()) {
        const trailing = consumeSseBuffer(`${buffer}\n\n`)
        for (const ev of trailing.events) {
          handlers.onEvent(ev)
        }
      }
      handlers.onClose?.()
    } catch (error) {
      if ((error as { name?: string })?.name === 'AbortError') {
        handlers.onClose?.()
        return
      }
      handlers.onError?.(error)
    }
  },
}
