import { useRef, useState } from 'react'

import { api } from '../services/api'
import type { ChatResponse } from '../types'

export interface ChatMessage {
  id: string
  role: 'user' | 'agent'
  content: string
  createdAt: string
  model?: string
  sources?: Array<{ source: string; heading?: string; text?: string }>
  trace?: ChatResponse['trace']
}

function nextId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastFailedQuestion, setLastFailedQuestion] = useState<string | null>(null)
  const controllerRef = useRef<AbortController | null>(null)

  async function send(question: string): Promise<boolean> {
    const trimmed = question.trim()
    if (!trimmed || loading) return false

    const userMsgId = nextId('user')
    const now = new Date().toISOString()
    setMessages((current) => [...current, { id: userMsgId, role: 'user', content: trimmed, createdAt: now }])
    setLoading(true)
    setError(null)
    setLastFailedQuestion(null)

    const controller = new AbortController()
    controllerRef.current = controller

    try {
      const response = await api.chat(trimmed, controller.signal)
      setMessages((current) => [
        ...current,
        {
          id: response.request_id || nextId('agent'),
          role: 'agent',
          content: response.answer_markdown,
          createdAt: new Date().toISOString(),
          model: response.model,
          sources: response.sources,
          trace: response.trace,
        },
      ])
      return true
    } catch (err) {
      // Remove the uncommitted user bubble so retrying or editing does not duplicate it.
      setMessages((current) => current.filter((msg) => msg.id !== userMsgId))
      const isAbort = (err instanceof DOMException && err.name === 'AbortError')
        || (err instanceof Error && err.name === 'AbortError')
      if (!isAbort) {
        setError((err as Error).message)
        setLastFailedQuestion(trimmed)
      }
      return false
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null
      setLoading(false)
    }
  }

  function stop() {
    controllerRef.current?.abort()
    controllerRef.current = null
  }

  function clear() {
    stop()
    setMessages([])
    setError(null)
    setLastFailedQuestion(null)
  }

  return { messages, loading, error, lastFailedQuestion, send, stop, clear }
}
