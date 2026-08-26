import { Bot, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { useTranslation } from 'react-i18next'

import { api } from '../services/api'
import type { CoachAction, CoachActionResponse, CoachSurface } from '../types'

interface CoachPanelProps {
  surface: CoachSurface
  date?: string
  question?: string
  requestAction?: (action: CoachAction) => Promise<CoachActionResponse>
  disabled?: boolean
  actions: Array<{ action: CoachAction; label: string }>
}

export function CoachPanel({ surface, date, question, requestAction, disabled = false, actions }: CoachPanelProps) {
  const { t } = useTranslation()
  const [answer, setAnswer] = useState<CoachActionResponse | null>(null)
  const [loading, setLoading] = useState<CoachAction | null>(null)
  const [error, setError] = useState<string | null>(null)
  const requestGeneration = useRef(0)
  const requestActionRef = useRef(requestAction)
  requestActionRef.current = requestAction

  useEffect(() => {
    requestGeneration.current += 1
    setAnswer(null)
    setLoading(null)
    setError(null)
    return () => { requestGeneration.current += 1 }
  }, [date, question, surface])

  async function run(action: CoachAction) {
    const generation = ++requestGeneration.current
    setLoading(action)
    setAnswer(null)
    setError(null)
    try {
      const response = requestActionRef.current
        ? await requestActionRef.current(action)
        : await api.coachAction({
          surface,
          action,
          ...(date ? { date } : {}),
          ...(question ? { question } : {}),
        })
      if (requestGeneration.current === generation) setAnswer(response)
    } catch (err) {
      if (requestGeneration.current === generation) setError((err as Error).message)
    } finally {
      if (requestGeneration.current === generation) setLoading(null)
    }
  }

  return (
    <div className="coach-panel">
      <header>
        <Bot size={20} />
        <div>
          <span>{t('coach.eyebrow')}</span>
          <h2>{t('coach.title')}</h2>
        </div>
      </header>
      <div className="coach-actions">
        {actions.map((item) => (
          <button key={item.action} type="button" onClick={() => void run(item.action)} disabled={disabled || loading !== null}>
            <Sparkles size={16} />
            {loading === item.action ? t('coach.thinking') : item.label}
          </button>
        ))}
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      {answer ? <div className="coach-answer"><ReactMarkdown>{answer.answer_markdown}</ReactMarkdown></div> : (
        <p className="coach-empty">{t('coach.empty')}</p>
      )}
    </div>
  )
}
