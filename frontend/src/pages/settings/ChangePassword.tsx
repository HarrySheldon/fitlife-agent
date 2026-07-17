import { ArrowLeft, CheckCircle2, KeyRound } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { useAuth } from '../../hooks/useAuth'
import { api } from '../../services/api'

type Feedback = { kind: 'success' | 'error'; message: string }

export function ChangePassword() {
  const { t } = useTranslation()
  const { replaceSession } = useAuth()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const feedbackRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    feedbackRef.current?.focus()
  }, [feedback])

  const canSubmit = Boolean(currentPassword && newPassword && confirmation && newPassword === confirmation)
  const confirmationMismatch = Boolean(confirmation && newPassword !== confirmation)

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSubmit) {
      setFeedback({ kind: 'error', message: t('settingsPassword.mismatch') })
      return
    }

    setSubmitting(true)
    setFeedback(null)
    try {
      const session = await api.changePassword({ current_password: currentPassword, new_password: newPassword })
      replaceSession(session)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmation('')
      setFeedback({ kind: 'success', message: t('settingsPassword.changed') })
    } catch (error) {
      setFeedback({ kind: 'error', message: error instanceof Error ? error.message : t('settingsPassword.failed') })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="page-stack settings-page">
      <header className="settings-task-header">
        <Link className="icon-button" to="/settings/security" aria-label={t('common.back')}>
          <ArrowLeft size={19} />
        </Link>
        <div className="page-header">
          <span>{t('settingsSecurity.title')}</span>
          <h1>{t('settingsPassword.title')}</h1>
        </div>
      </header>

      <form className="settings-form" onSubmit={(event) => void submit(event)} aria-busy={submitting}>
        <section className="settings-section">
          <div className="settings-section-heading">
            <KeyRound size={19} />
            <h2>{t('settingsPassword.credentials')}</h2>
            <p>{t('settingsPassword.description')}</p>
          </div>
          <div className="settings-section-control">
            <label className="settings-field">
              <span>{t('settingsPassword.current')}</span>
              <input name="current-password" type="password" autoComplete="current-password" maxLength={128} required value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} />
            </label>
            <label className="settings-field">
              <span>{t('settingsPassword.new')}</span>
              <input name="new-password" type="password" autoComplete="new-password" minLength={8} maxLength={128} required value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
            </label>
            <label className="settings-field">
              <span>{t('settingsPassword.confirm')}</span>
              <input name="confirm-password" type="password" autoComplete="new-password" minLength={8} maxLength={128} required aria-invalid={confirmationMismatch} aria-describedby={confirmationMismatch ? 'password-confirmation-error' : undefined} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} />
              {confirmationMismatch ? <span id="password-confirmation-error" className="settings-inline-error">{t('settingsPassword.mismatch')}</span> : null}
            </label>
          </div>
        </section>

        {feedback ? (
          <div ref={feedbackRef} className={`settings-feedback ${feedback.kind}`} role={feedback.kind === 'error' ? 'alert' : 'status'} tabIndex={-1}>
            {feedback.kind === 'success' ? <CheckCircle2 size={18} aria-hidden="true" /> : null}
            {feedback.message}
          </div>
        ) : null}

        <footer className="settings-actions">
          <button className="primary-button" type="submit" disabled={submitting || !canSubmit}>
            <KeyRound size={17} aria-hidden="true" />
            {submitting ? t('settingsPassword.changing') : t('settingsPassword.submit')}
          </button>
        </footer>
      </form>
    </div>
  )
}
