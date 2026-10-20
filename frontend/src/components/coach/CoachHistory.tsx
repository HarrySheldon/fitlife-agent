import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useCoach } from '../../hooks/useCoach'

export function CoachHistory() {
  const coach = useCoach()
  const { t } = useTranslation()
  const [deleting, setDeleting] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [working, setWorking] = useState(false)
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    if (!deleting || !dialog.current) return
    const returnFocus = document.activeElement as HTMLElement | null
    dialog.current.showModal?.()
    dialog.current.querySelector<HTMLButtonElement>('button')?.focus()
    return () => { returnFocus?.focus() }
  }, [deleting])
  if (!coach) return null
  return <>
    <nav className="coach-history" aria-label={t('coachConversation.history')}>
      {coach.conversations.map(item => <div key={item.conversation_id} className="coach-history-row">
        <button type="button" aria-current={item.conversation_id === coach.selected ? 'true' : undefined} onClick={() => coach.setSelected(item.conversation_id)}>{item.title || t('coachConversation.newChat')}</button>
        <button type="button" onClick={() => { setEditing(item.conversation_id); setTitle(item.title ?? '') }}>{t('coachConversation.rename')}</button>
        <button type="button" onClick={() => setDeleting(item.conversation_id)}>{t('coachConversation.delete')}</button>
        {editing === item.conversation_id ? <form onSubmit={event => { event.preventDefault(); if (working) return; setWorking(true); void coach.rename(item.conversation_id, title).finally(() => { setWorking(false); setEditing(null) }) }}>
          <label>{t('coachConversation.chatTitle')}<input autoFocus maxLength={120} value={title} onChange={event => setTitle(event.target.value)} /></label>
          <button disabled={working} type="submit">{t('coachConversation.save')}</button>
          <button type="button" onClick={() => setEditing(null)}>{t('coachConversation.cancel')}</button>
        </form> : null}
      </div>)}
    </nav>
    {deleting ? <dialog ref={dialog} className="coach-delete-dialog" aria-labelledby="coach-delete-title" onCancel={event => { event.preventDefault(); if (!working) setDeleting(null) }}>
      <h3 id="coach-delete-title">{t('coachConversation.deleteTitle')}</h3>
      <p>{t('coachConversation.deleteNotice')}</p>
      <button type="button" disabled={working} onClick={() => setDeleting(null)}>{t('coachConversation.cancel')}</button>
      <button type="button" disabled={working} onClick={() => { if (!deleting) return; setWorking(true); void coach.remove(deleting).finally(() => { setWorking(false); setDeleting(null) }) }}>{t('coachConversation.stopAndDelete')}</button>
    </dialog> : null}
  </>
}
