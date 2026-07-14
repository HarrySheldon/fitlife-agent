import { Send } from 'lucide-react'
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { useTranslation } from 'react-i18next'

import type { ChatMessage } from '../hooks/useChat'

interface ChatBoxProps {
  messages: ChatMessage[]
  loading: boolean
  onSend: (question: string) => Promise<void>
}

export function ChatBox({ messages, loading, onSend }: ChatBoxProps) {
  const { t } = useTranslation()
  const [question, setQuestion] = useState('')

  async function submit() {
    const value = question.trim()
    if (!value) return
    setQuestion('')
    await onSend(value)
  }

  return (
    <section className="chat-panel">
      <div className="message-list">
        {messages.map((message, index) => (
          <article key={index} className={`message ${message.role}`}>
            <ReactMarkdown>{message.content}</ReactMarkdown>
            {message.trace ? <small>{t('components.tools')} {message.trace.tool_calls.join(', ')}</small> : null}
          </article>
        ))}
        {loading ? <article className="message agent">{t('components.agentThinking')}</article> : null}
      </div>
      <div className="composer">
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void submit()
          }}
          placeholder={t('components.chatPlaceholder')}
        />
        <button type="button" onClick={() => void submit()} aria-label={t('components.sendQuestion')}>
          <Send size={18} />
        </button>
      </div>
    </section>
  )
}
