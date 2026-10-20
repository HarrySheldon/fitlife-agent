import { Bot, Maximize2, Minimize2, Plus, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useCoach } from '../../hooks/useCoach'
import { holdsCoachSlot } from '../../types/coach'
import { CoachComposer } from './CoachComposer'
import { CoachMessages } from './CoachMessages'
import { CoachHistory } from './CoachHistory'

export function CoachWindow() {
  const coach = useCoach()
  const { t } = useTranslation()
  const launcher = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLElement>(null)
  const [history, setHistory] = useState(false)
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null)
  const drag = useRef<{ x: number; y: number } | null>(null)
  useEffect(() => {
    if (!coach?.open) return
    panel.current?.focus()
    return () => { launcher.current?.focus() }
  }, [coach?.open])
  useEffect(() => {
    const reset = () => setPosition(null)
    window.addEventListener('resize', reset)
    return () => window.removeEventListener('resize', reset)
  }, [])
  if (!coach) return null
  const busy = holdsCoachSlot(coach.active)
  const selected = coach.conversations.find(item => item.conversation_id === coach.selected)
  const failed = coach.lastTurn?.conversation_id === coach.selected
    && ['failed', 'interrupted', 'cancelled', 'timed_out'].includes(coach.lastTurn.status)
    ? coach.lastTurn : null
  const retryQuestion = failed ? coach.messages.find(message => message.turn_id === failed.turn_id && message.role === 'user')?.body : null
  return <>
    <button ref={launcher} type="button" className="coach-launcher" aria-expanded={coach.open} aria-controls="coach-window" onClick={coach.show}>
      <Bot size={21} />{t('coach.title')}{busy ? <span>{t('coachConversation.running')}</span> : coach.unread ? <span>{t('coachConversation.unread')}</span> : null}
    </button>
    <section id="coach-window" ref={panel} hidden={!coach.open} role="dialog" aria-label={t('coach.title')} tabIndex={-1}
      className={`coach-window${coach.maximized ? ' coach-window-maximized' : ''}`}
      style={position && !coach.maximized ? { left: position.x, top: position.y, transform: 'none' } : undefined}
      onKeyDown={event => { if (event.key === 'Escape' && !(event.target as HTMLElement).closest('dialog')) { coach.setOpen(false); launcher.current?.focus() } }}>
      <header className="coach-window-header"
        onPointerDown={event => {
          if (coach.maximized || window.innerWidth < 768 || (event.target as HTMLElement).closest('button')) return
          const rect = panel.current!.getBoundingClientRect()
          drag.current = { x: event.clientX - rect.left, y: event.clientY - rect.top }
          event.currentTarget.setPointerCapture(event.pointerId)
        }}
        onPointerMove={event => {
          if (!drag.current || !panel.current) return
          const rect = panel.current.getBoundingClientRect()
          setPosition({ x: Math.max(8, Math.min(window.innerWidth - rect.width - 8, event.clientX - drag.current.x)), y: Math.max(8, Math.min(window.innerHeight - rect.height - 8, event.clientY - drag.current.y)) })
        }}
        onPointerUp={() => { drag.current = null }} onPointerCancel={() => { drag.current = null }}>
        <div><span>{t('coachConversation.brand')}</span><h2>{selected?.title || t('coachConversation.newChat')}</h2></div>
        <nav aria-label={t('coachConversation.controls')}>
          <button type="button" onClick={() => setHistory(!history)}>{t('coachConversation.history')}</button>
          <button type="button" aria-label={t('coachConversation.newChat')} onClick={coach.newChat}><Plus size={18} /></button>
          <button type="button" aria-label={t('coachConversation.maximize')} onClick={() => coach.setMaximized(!coach.maximized)}>{coach.maximized ? <Minimize2 size={18} /> : <Maximize2 size={18} />}</button>
          <button type="button" aria-label={t('coachConversation.minimize')} onClick={() => { coach.setOpen(false); launcher.current?.focus() }}><X size={18} /></button>
        </nav>
      </header>
      {history ? <CoachHistory /> : null}
      <CoachMessages messages={coach.messages} conversation={coach.selected} visible={coach.open} />
      <div className="coach-turn-status" role="status">
        {busy ? <><span>{t(coach.active?.stopping ? 'coachConversation.stopping' : 'coachConversation.running')}</span>
          {coach.active?.conversation_id !== coach.selected ? <button type="button" onClick={() => coach.setSelected(coach.active!.conversation_id)}>{t('coachConversation.goActive')}</button> : null}
          <button type="button" disabled={coach.active?.stopping} onClick={() => void coach.stop()}>{t('coachConversation.stop')}</button></> : null}
        {coach.lastTurn && coach.lastTurn.conversation_id === coach.selected && !busy && coach.lastTurn.status !== 'succeeded' ? <span>{t(`coachConversation.states.${coach.lastTurn.status}`)}</span> : null}
        {coach.notice ? <small>{coach.notice}</small> : null}
      </div>
      {coach.error ? <p className="form-error" role="alert">{t('coachConversation.error')}</p> : null}
      {failed && retryQuestion ? <div className="coach-retry"><small>{t('coachConversation.retryNotice')}</small><button type="button" disabled={busy || coach.sending} onClick={() => {
        if (failed.receipt?.context) {
          const context = failed.receipt.context
          void coach.send({ question: retryQuestion, action: context.action, surface: context.surface,
            date: context.date ?? undefined, plan_id: context.plan_id ?? undefined,
            report_week: context.report_week ?? undefined, language: context.language,
            answer_mode: context.answer_mode })
        }
        else coach.setDraft(retryQuestion)
      }}>{t(failed.receipt?.context ? 'coachConversation.retry' : 'coachConversation.editQuestion')}</button></div> : null}
      <p className="coach-history-notice">{t('coachConversation.historical')}</p>
      <CoachComposer value={coach.draft} onChange={coach.setDraft} disabled={busy || coach.sending} onSend={() => void coach.send({ question: coach.draft, action: 'chat', surface: 'today' })} />
    </section>
  </>
}
