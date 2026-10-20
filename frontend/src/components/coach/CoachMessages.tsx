import { useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import ReactMarkdown from 'react-markdown'
import type { CoachMessage } from '../../types/coach'

// Keep this component mounted while hidden so reading position survives minimize.
export function CoachMessages({ messages, conversation, visible = true }: { messages: CoachMessage[]; conversation: string | null; visible?: boolean }) {
  const { t } = useTranslation()
  const list = useRef<HTMLDivElement>(null)
  const positions = useRef<Record<string, number>>({})
  const follow = useRef(true)
  const previous = useRef(conversation)
  const lastVisible = useRef(visible)
  const [newMessage, setNewMessage] = useState(false)
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
    } else if (!lastVisible.current) element.scrollTop = positions.current[conversation ?? 'new'] ?? fallback
    else if (follow.current) element.scrollTop = element.scrollHeight
    else setNewMessage(true)
    follow.current = element.scrollHeight - element.scrollTop - element.clientHeight < 48
    lastVisible.current = visible
  }, [messages, conversation, visible])
  return <div className="coach-transcript-wrap">
    <div ref={list} className="coach-transcript" role="log" aria-label={t('coachConversation.messages')} aria-live="polite"
      onScroll={event => {
        const element = event.currentTarget
        positions.current[conversation ?? 'new'] = element.scrollTop
        follow.current = element.scrollHeight - element.scrollTop - element.clientHeight < 48
        if (follow.current) setNewMessage(false)
      }}>
      {!messages.length ? <div className="coach-welcome"><span>{t('coachConversation.brand')}</span><h3>{t('coachConversation.welcome')}</h3><p>{t('coachConversation.privacy')}</p></div> : messages.map(message => <article key={message.message_id} className={`coach-message coach-message-${message.role}`}>
        <header>{t(message.role === 'user' ? 'coachConversation.you' : 'coach.title')} <time dateTime={message.created_at}>{new Date(message.created_at).toLocaleString()}</time></header>
        <ReactMarkdown>{message.body}</ReactMarkdown>
        {message.role === 'coach' ? <footer className="coach-message-context">
          <small>{t('coachConversation.advice')}</small>
          {message.metadata?.business_task_ref ? <p className="coach-business-task" data-testid="coach-business-task">
            {t('coachConversation.businessTask')}: {message.metadata.business_task_ref.kind} · {message.metadata.business_task_ref.task_id}
          </p> : null}
          {message.metadata?.context ? <p>{t('coachConversation.context')}: {[message.metadata.context.date, message.metadata.context.plan_id, message.metadata.context.report_week].filter(Boolean).join(' · ') || t('coachConversation.recentOnly')}</p> : null}
          {message.metadata?.sources?.length ? <div><small>{t('coachConversation.sources')}</small><ul>{message.metadata.sources.map((source, index) => <li key={index}>{source.heading || source.source}</li>)}</ul></div> : null}
          <details><summary>{t('coachConversation.technical')}</summary><small>{message.metadata?.model ?? '—'} · {message.turn_id}</small></details>
        </footer> : null}
      </article>)}
    </div>
    {newMessage ? <button className="coach-jump" type="button" onClick={() => { if (list.current) { list.current.scrollTop = list.current.scrollHeight; positions.current[conversation ?? 'new'] = list.current.scrollTop } follow.current = true; setNewMessage(false) }}>{t('coachConversation.newReply')}</button> : null}
  </div>
}
