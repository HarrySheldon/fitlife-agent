import {
  Bot,
  CalendarPlus,
  CheckCircle2,
  Dumbbell,
  MessageSquarePlus,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
  Utensils,
} from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import ReactMarkdown from 'react-markdown'
import { Link, useSearchParams } from 'react-router-dom'

import { ErrorState } from '../components/ErrorState'
import { useChat } from '../hooks/useChat'
import { useCoach } from '../hooks/useCoach'
import { weeklyAutomationApi } from '../services/weeklyAutomationApi'
import type { CoachSurface } from '../types'

type ReadDomain = 'profile' | 'training' | 'diet'

const ALL_DOMAINS: ReadDomain[] = ['profile', 'training', 'diet']

function normalizeSurface(raw: string | null): CoachSurface {
  if (raw === 'today' || raw === 'logbook' || raw === 'review' || raw === 'plan' || raw === 'profile') {
    return raw
  }
  if (raw === 'progress') return 'review'
  return 'today'
}

export function CoachPage() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const coach = useCoach()
  const fallbackChat = useChat()

  const initialPrompt = params.get('prompt') ?? ''
  const contextSurface = normalizeSurface(params.get('surface'))
  const contextDate = params.get('date') ?? undefined

  const [input, setInput] = useState(initialPrompt)
  const [readDomains, setReadDomains] = useState<ReadDomain[]>(['profile', 'training', 'diet'])
  const [generatingPlan, setGeneratingPlan] = useState(false)
  const [generatedDraftTitle, setGeneratedDraftTitle] = useState<string | null>(null)
  const [planError, setPlanError] = useState<string | null>(null)

  useEffect(() => {
    if (initialPrompt) {
      setInput(initialPrompt)
    }
  }, [initialPrompt])

  function toggleDomain(domain: ReadDomain) {
    setReadDomains((current) =>
      current.includes(domain)
        ? current.filter((d) => d !== domain)
        : [...current, domain],
    )
  }

  async function submitQuestion(text: string) {
    const trimmed = text.trim()
    if (!trimmed) return
    setInput('')
    if (coach) {
      await coach.send({
        question: trimmed,
        action: 'chat',
        surface: contextSurface,
        date: contextDate,
        read_domains: readDomains,
      })
    } else {
      await fallbackChat.send(trimmed)
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    void submitQuestion(input)
  }

  async function handleGeneratePersonalizedDraft() {
    setGeneratingPlan(true)
    setPlanError(null)
    setGeneratedDraftTitle(null)
    try {
      const res = await weeklyAutomationApi.generatePersonalizedDraft({
        duration_weeks: 4,
      })
      setGeneratedDraftTitle(res.cycle.title)
    } catch (cause) {
      setPlanError(cause instanceof Error ? cause.message : t('planCycle.createFailed'))
    } finally {
      setGeneratingPlan(false)
    }
  }

  const quickStarters = [
    {
      key: 'progress',
      icon: Sparkles,
      label: t('coachWorkbench.starters.progressTitle'),
      prompt: t('coachWorkbench.starters.progressPrompt'),
    },
    {
      key: 'substitution',
      icon: Dumbbell,
      label: t('coachWorkbench.starters.exerciseTitle'),
      prompt: t('coachWorkbench.starters.exercisePrompt'),
    },
    {
      key: 'food',
      icon: Utensils,
      label: t('coachWorkbench.starters.foodTitle'),
      prompt: t('coachWorkbench.starters.foodPrompt'),
    },
    {
      key: 'nutrition',
      icon: Bot,
      label: t('coachWorkbench.starters.nutritionTitle'),
      prompt: t('coachWorkbench.starters.nutritionPrompt'),
    },
  ]

  const isMultiChat = Boolean(coach)
  const busy = coach ? coach.sending || coach.active !== null : fallbackChat.loading
  const activeMessages = coach ? coach.messages : []

  return (
    <div className="page-stack coach-workbench-page">
      <header className="page-header inline-header">
        <div>
          <span>{t('coachWorkbench.eyebrow')}</span>
          <h1>{t('coachWorkbench.title')}</h1>
        </div>
        <div className="session-scope-bar" aria-label={t('coachWorkbench.readScopeLabel')}>
          <span className="scope-label">
            <ShieldCheck size={15} />
            {t('coachWorkbench.sessionScope')}:
          </span>
          {ALL_DOMAINS.map((domain) => {
            const enabled = readDomains.includes(domain)
            return (
              <button
                key={domain}
                type="button"
                className={`chip-toggle ${enabled ? 'selected' : ''}`}
                aria-pressed={enabled}
                onClick={() => toggleDomain(domain)}
              >
                {t(`coachWorkbench.domains.${domain}`)} {enabled ? '✓' : ''}
              </button>
            )
          })}
        </div>
      </header>

      <div className="coach-workbench-grid">
        <aside className="coach-workbench-rail">
          <section className="panel-card">
            <header className="section-card-header">
              <h2>{t('coachWorkbench.planActionTitle')}</h2>
              <p className="muted-copy">{t('coachWorkbench.planActionDesc')}</p>
            </header>
            <button
              type="button"
              className="primary-button"
              disabled={generatingPlan}
              onClick={() => void handleGeneratePersonalizedDraft()}
            >
              <CalendarPlus size={16} />
              {generatingPlan ? t('common.generating') : t('coachWorkbench.generatePlanDraft')}
            </button>
            {generatedDraftTitle ? (
              <div className="settings-feedback success" role="status">
                <CheckCircle2 size={16} />
                <div>
                  <strong>{t('coachWorkbench.draftCreated', { title: generatedDraftTitle })}</strong>
                  <div>
                    <Link className="text-link" to="/plan">
                      {t('weeklyAutomation.reviewDraft')} →
                    </Link>
                  </div>
                </div>
              </div>
            ) : null}
            {planError ? <ErrorState message={planError} /> : null}
          </section>

          {coach ? (
            <section className="panel-card">
              <header className="section-card-header inline-between">
                <h2>{t('coachConversation.history')}</h2>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => coach.newChat()}
                >
                  <MessageSquarePlus size={15} />
                  {t('coachConversation.newChat')}
                </button>
              </header>
              <ul className="coach-conv-list">
                {coach.conversations.map((conv) => (
                  <li
                    key={conv.conversation_id}
                    className={coach.selected === conv.conversation_id ? 'active' : ''}
                  >
                    <button
                      type="button"
                      className="conv-select-btn"
                      onClick={() => coach.setSelected(conv.conversation_id)}
                    >
                      {conv.title || t('coachConversation.newChat')}
                    </button>
                    <button
                      type="button"
                      className="icon-button"
                      aria-label={t('coachConversation.delete')}
                      onClick={() => void coach.remove(conv.conversation_id)}
                    >
                      <Trash2 size={14} />
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <section className="panel-card">
            <h2>{t('coachWorkbench.quickStartersTitle')}</h2>
            <div className="starter-list">
              {quickStarters.map(({ key, icon: Icon, label, prompt }) => (
                <button
                  key={key}
                  type="button"
                  className="starter-card"
                  disabled={busy}
                  onClick={() => void submitQuestion(prompt)}
                >
                  <Icon size={16} />
                  <span>{label}</span>
                </button>
              ))}
            </div>
          </section>
        </aside>

        <section className="panel-card coach-workbench-main" aria-label={t('coachConversation.messages')}>
          {!isMultiChat && fallbackChat.error ? <ErrorState message={fallbackChat.error} /> : null}
          {isMultiChat && coach?.error ? <ErrorState message={t('coachConversation.error')} /> : null}

          <div className="coach-thread">
            {isMultiChat ? (
              activeMessages.length ? (
                activeMessages.map((msg) => (
                  <article key={msg.message_id} className={`coach-bubble ${msg.role}`}>
                    <header className="coach-bubble-meta">
                      <strong>{msg.role === 'user' ? t('coachConversation.you') : t('coach.title')}</strong>
                    </header>
                    <div className="coach-bubble-body">
                      <ReactMarkdown>{msg.body}</ReactMarkdown>
                    </div>
                    {msg.metadata?.sources && msg.metadata.sources.length > 0 ? (
                      <footer className="coach-bubble-sources">
                        <span>{t('coachConversation.sources')}: </span>
                        {msg.metadata.sources.map((src, idx) => (
                          <code key={idx}>{src.source}</code>
                        ))}
                      </footer>
                    ) : null}
                  </article>
                ))
              ) : (
                <div className="cold-start-box">
                  <Bot size={26} />
                  <p>{t('coachWorkbench.emptyPrompt')}</p>
                </div>
              )
            ) : fallbackChat.messages.length ? (
              fallbackChat.messages.map((msg, idx) => (
                <article key={`${msg.role}-${idx}`} className={`coach-bubble ${msg.role}`}>
                  <header className="coach-bubble-meta">
                    <strong>{msg.role === 'user' ? t('coachConversation.you') : t('coach.title')}</strong>
                  </header>
                  <div className="coach-bubble-body">
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                  </div>
                </article>
              ))
            ) : (
              <div className="cold-start-box">
                <Bot size={26} />
                <p>{t('coachWorkbench.emptyPrompt')}</p>
              </div>
            )}
            {busy ? <p className="muted-copy">{t('components.agentThinking')}</p> : null}
          </div>

          <form className="coach-composer" onSubmit={handleSubmit}>
            <textarea
              rows={2}
              aria-label={t('coachConversation.question')}
              placeholder={t('components.chatPlaceholder')}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  void submitQuestion(input)
                }
              }}
            />
            <button type="submit" className="primary-button" disabled={busy || !input.trim()}>
              <Send size={15} />
              {t('coachConversation.send')}
            </button>
          </form>
        </section>
      </div>
    </div>
  )
}
