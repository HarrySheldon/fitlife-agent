import { CalendarPlus, Check, Copy } from 'lucide-react'
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import ReactMarkdown from 'react-markdown'
import type { CoachMessage } from '../../types/coach'

interface Props {
  messages: CoachMessage[]
  conversation: string | null
  visible?: boolean
  onOpenTask?: (taskId: string) => void
  onGeneratePlanFromAnswer?: (answerBody: string) => void
  generatingPlan?: boolean
  emptyState?: ReactNode
}

// Keep this component mounted while hidden so reading position survives minimize.
export function CoachMessages({
  messages,
  conversation,
  visible = true,
  onOpenTask,
  onGeneratePlanFromAnswer,
  generatingPlan = false,
  emptyState,
}: Props) {
  const { t } = useTranslation()
  const list = useRef<HTMLDivElement>(null)
  const positions = useRef<Record<string, number>>({})
  const follow = useRef(true)
  const previous = useRef(conversation)
  const lastVisible = useRef(visible)
  const [newMessage, setNewMessage] = useState(false)
  const [copiedId, setCopiedId] = useState<string | null>(null)

  useLayoutEffect(() => {
    const element = list.current
    if (!element || !visible) { lastVisible.current = visible; return }
    // An empty chat shows the welcome card; bottom-aligning it clips the heading
    // when the viewport is short (for example at 200% zoom).
    const fallback = messages.length ? element.scrollHeight : 0
    if (previous.current !== conversation) {
      element.scrollTop = positions.current[conversation ?? 'new'] ?? fallback
      previous.current = conversation
      setNewMessage(false)
    } else if (!lastVisible.current) {
      element.scrollTop = positions.current[conversation ?? 'new'] ?? fallback
    } else if (follow.current) {
      element.scrollTop = element.scrollHeight
    } else {
      setNewMessage(true)
    }
    follow.current = element.scrollHeight - element.scrollTop - element.clientHeight < 48
    lastVisible.current = visible
  }, [messages, conversation, visible])

  function handleCopy(messageId: string, text: string) {
    if (navigator.clipboard?.writeText) {
      void navigator.clipboard.writeText(text).then(() => {
        setCopiedId(messageId)
        window.setTimeout(() => {
          setCopiedId(current => (current === messageId ? null : current))
        }, 2000)
      }).catch(() => undefined)
    }
  }

  return (
    <div className="coach-transcript-wrap">
      <div
        ref={list}
        className="coach-transcript"
        role="log"
        aria-label={t('coachConversation.messages')}
        aria-live="polite"
        onScroll={event => {
          const element = event.currentTarget
          positions.current[conversation ?? 'new'] = element.scrollTop
          follow.current = element.scrollHeight - element.scrollTop - element.clientHeight < 48
          if (follow.current) setNewMessage(false)
        }}
      >
        {!messages.length ? (
          emptyState ?? (
            <div className="coach-welcome">
              <span>{t('coachConversation.brand')}</span>
              <h3>{t('coachConversation.welcome')}</h3>
              <p>{t('coachConversation.privacy')}</p>
            </div>
          )
        ) : (
          messages.map(message => (
            <article key={message.message_id} className={`coach-message coach-message-${message.role}`}>
              <header>
                <span>{t(message.role === 'user' ? 'coachConversation.you' : 'coach.title')}</span>
                <time dateTime={message.created_at}>{new Date(message.created_at).toLocaleString()}</time>
              </header>
              <div className="coach-message-body">
                <ReactMarkdown>{message.body}</ReactMarkdown>
              </div>
              {message.role === 'coach' ? (
                <footer className="coach-message-context">
                  <small>{t('coachConversation.advice')}</small>
                  {message.metadata?.business_task_ref ? (
                    <p className="coach-business-task" data-testid="coach-business-task">
                      {t('coachConversation.businessTask')}: {message.metadata.business_task_ref.kind} · {message.metadata.business_task_ref.task_id}
                      {message.metadata.business_task_ref.kind === 'plan_adjustment' && onOpenTask ? (
                        <button type="button" onClick={() => onOpenTask(message.metadata!.business_task_ref!.task_id)}>
                          {t('plan.planTask.open')}
                        </button>
                      ) : null}
                    </p>
                  ) : null}
                  {message.metadata?.context ? (
                    <p>
                      {t('coachConversation.context')}: {[
                        message.metadata.context.date,
                        message.metadata.context.plan_id,
                        message.metadata.context.report_week,
                      ].filter(Boolean).join(' · ') || t('coachConversation.recentOnly')}
                    </p>
                  ) : null}
                  {message.metadata?.sources?.length ? (
                    <div className="coach-sources-block">
                      <small>{t('coachConversation.sources')}</small>
                      <ul>
                        {message.metadata.sources.map((source, index) => (
                          <li key={index}>{source.heading || source.source}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  <div className="coach-message-footer-row">
                    <details>
                      <summary>{t('coachConversation.technical')}</summary>
                      <small>{message.metadata?.model ?? '—'} · {message.turn_id}</small>
                    </details>
                    <div className="coach-message-actions">
                      <button
                        type="button"
                        className="ghost-action-btn"
                        onClick={() => handleCopy(message.message_id, message.body)}
                      >
                        {copiedId === message.message_id ? <Check size={13} /> : <Copy size={13} />}
                        {t(copiedId === message.message_id ? 'coachWorkbench.copiedAnswer' : 'coachWorkbench.copyAnswer')}
                      </button>
                      {onGeneratePlanFromAnswer ? (
                        <button
                          type="button"
                          className="ghost-action-btn"
                          disabled={generatingPlan}
                          onClick={() => onGeneratePlanFromAnswer(message.body)}
                        >
                          <CalendarPlus size={13} />
                          {t('coachWorkbench.draftFromAnswer')}
                        </button>
                      ) : null}
                    </div>
                  </div>
                </footer>
              ) : null}
            </article>
          ))
        )}
      </div>
      {newMessage ? (
        <button
          className="coach-jump"
          type="button"
          onClick={() => {
            if (list.current) {
              list.current.scrollTop = list.current.scrollHeight
              positions.current[conversation ?? 'new'] = list.current.scrollTop
            }
            follow.current = true
            setNewMessage(false)
          }}
        >
          {t('coachConversation.newReply')}
        </button>
      ) : null}
    </div>
  )
}
