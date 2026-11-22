import { Send, Square } from 'lucide-react'
import { useRef } from 'react'
import { useTranslation } from 'react-i18next'

interface Props {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  disabled: boolean
  placeholder?: string
  inputId?: string
  busy?: boolean
  stopping?: boolean
  onStop?: () => void
}

export function CoachComposer({
  value,
  onChange,
  onSend,
  disabled,
  placeholder,
  inputId = 'coach-question',
  busy = false,
  stopping = false,
  onStop,
}: Props) {
  const { t } = useTranslation()
  const composing = useRef(false)
  return (
    <form
      className="coach-composer"
      onSubmit={event => {
        event.preventDefault()
        if (!disabled && value.trim()) onSend()
      }}
    >
      <label className="coach-composer-label" htmlFor={inputId}>
        {t('coachConversation.question')}
      </label>
      <textarea
        id={inputId}
        rows={3}
        maxLength={1000}
        placeholder={placeholder}
        value={value}
        onChange={event => onChange(event.target.value)}
        onCompositionStart={() => { composing.current = true }}
        onCompositionEnd={() => { composing.current = false }}
        onKeyDown={event => {
          if (
            event.key === 'Enter'
            && !event.shiftKey
            && !composing.current
            && !event.nativeEvent.isComposing
            && event.keyCode !== 229
          ) {
            event.preventDefault()
            if (!disabled && value.trim()) onSend()
          }
        }}
      />
      <div className="coach-composer-footer">
        <small>{t('coachConversation.keyboard')} · {value.length}/1000</small>
        <div className="coach-composer-actions">
          {busy && onStop ? (
            <button
              type="button"
              className="secondary-button compact-btn"
              disabled={stopping}
              onClick={onStop}
            >
              <Square size={14} />
              {t('coachConversation.stop')}
            </button>
          ) : null}
          <button type="submit" className="primary-button" disabled={disabled || !value.trim()}>
            <Send size={15} />
            {t('coachConversation.send')}
          </button>
        </div>
      </div>
    </form>
  )
}
