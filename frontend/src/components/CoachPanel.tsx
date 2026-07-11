import { Bot, Sparkles } from 'lucide-react'
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'

import { api } from '../services/api'
import type { CoachAction, CoachActionResponse, CoachSurface } from '../types'

interface CoachPanelProps {
  surface: CoachSurface
  date?: string
  actions: Array<{ action: CoachAction; label: string }>
}

export function CoachPanel({ surface, date, actions }: CoachPanelProps) {
  const [answer, setAnswer] = useState<CoachActionResponse | null>(null)
  const [loading, setLoading] = useState<CoachAction | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function run(action: CoachAction) {
    setLoading(action)
    setError(null)
    try {
      setAnswer(await api.coachAction({ surface, action, date }))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(null)
    }
  }

  return (
    <aside className="coach-panel">
      <header>
        <Bot size={20} />
        <div>
          <span>Contextual guidance</span>
          <h2>Coach</h2>
        </div>
      </header>
      <div className="coach-actions">
        {actions.map((item) => (
          <button key={item.action} type="button" onClick={() => void run(item.action)} disabled={loading !== null}>
            <Sparkles size={16} />
            {loading === item.action ? 'Thinking...' : item.label}
          </button>
        ))}
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      {answer ? <div className="coach-answer"><ReactMarkdown>{answer.answer_markdown}</ReactMarkdown></div> : (
        <p className="coach-empty">Choose an action to analyze the records visible on this page.</p>
      )}
    </aside>
  )
}
