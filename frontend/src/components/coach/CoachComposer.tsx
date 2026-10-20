import { useRef } from 'react'
import { useTranslation } from 'react-i18next'

interface Props {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  disabled: boolean
}
export function CoachComposer({ value, onChange, onSend, disabled }: Props) {
  const { t } = useTranslation()
  const composing = useRef(false)
  return <form className="coach-composer" onSubmit={event => { event.preventDefault(); if (!disabled && value.trim()) onSend() }}>
    <label htmlFor="coach-question">{t('coachConversation.question')}</label>
    <textarea id="coach-question" rows={3} maxLength={1000} value={value}
      onChange={event => onChange(event.target.value)}
      onCompositionStart={() => { composing.current = true }}
      onCompositionEnd={() => { composing.current = false }}
      onKeyDown={event => {
        if (event.key === 'Enter' && !event.shiftKey && !composing.current && !event.nativeEvent.isComposing && event.keyCode !== 229) {
          event.preventDefault()
          if (!disabled && value.trim()) onSend()
        }
      }} />
    <div className="coach-composer-footer"><small>{t('coachConversation.keyboard')} · {value.length}/1000</small>
      <button type="submit" className="primary-button" disabled={disabled || !value.trim()}>{t('coachConversation.send')}</button>
    </div>
  </form>
}
