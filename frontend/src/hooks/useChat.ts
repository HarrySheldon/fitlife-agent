import { useState } from 'react'

import { api } from '../services/api'
import type { ChatResponse } from '../types'

export interface ChatMessage {
  role: 'user' | 'agent'
  content: string
  trace?: ChatResponse['trace']
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function send(question: string) {
    if (!question.trim()) return
    setMessages((current) => [...current, { role: 'user', content: question }])
    setLoading(true)
    setError(null)
    try {
      const response = await api.chat(question)
      setMessages((current) => [
        ...current,
        { role: 'agent', content: response.answer_markdown, trace: response.trace },
      ])
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return { messages, loading, error, send }
}
