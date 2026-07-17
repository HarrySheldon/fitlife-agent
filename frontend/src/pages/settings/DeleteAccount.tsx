import { AlertTriangle, ArrowLeft, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { useAuth } from '../../hooks/useAuth'
import { api } from '../../services/api'

export function DeleteAccount() {
  const { t } = useTranslation()
  const { logout } = useAuth()
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const errorRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    errorRef.current?.focus()
  }, [error])

  const canSubmit = Boolean(password && confirmation === 'DELETE')

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSubmit) return

    setDeleting(true)
    setError(null)
    try {
      await api.deleteAccount({ password, confirmation: 'DELETE' })
      logout()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('settingsDelete.failed'))
      setDeleting(false)
    }
  }

  return (
    <div className="page-stack settings-page delete-account-page">
      <header className="settings-task-header">
        <Link className="icon-button" to="/settings/privacy" aria-label={t('common.back')}>
          <ArrowLeft size={19} />
        </Link>
        <div className="page-header">
          <span>{t('settingsPrivacy.title')}</span>
          <h1>{t('settingsDelete.title')}</h1>
        </div>
      </header>

      <form className="settings-form" onSubmit={(event) => void submit(event)} aria-busy={deleting}>
        <section className="settings-section settings-danger-section">
          <div className="settings-section-heading">
            <Trash2 size={19} />
            <h2>{t('settingsDelete.permanent')}</h2>
            <p>{t('settingsDelete.description')}</p>
          </div>
          <div className="settings-section-control">
            <div className="settings-danger-note" role="note">
              <AlertTriangle size={18} aria-hidden="true" />
              <span>{t('settingsDelete.warning')}</span>
            </div>
            <label className="settings-field">
              <span>{t('settingsDelete.password')}</span>
              <input name="delete-password" type="password" autoComplete="current-password" maxLength={128} required value={password} onChange={(event) => setPassword(event.target.value)} />
            </label>
            <label className="settings-field">
              <span>{t('settingsDelete.confirmation')}</span>
              <input name="delete-confirmation" type="text" autoComplete="off" maxLength={32} required spellCheck={false} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} />
            </label>
          </div>
        </section>

        {error ? <div ref={errorRef} className="settings-feedback error" role="alert" tabIndex={-1}>{error}</div> : null}

        <footer className="settings-actions">
          <button className="danger-button" type="submit" disabled={deleting || !canSubmit}>
            <Trash2 size={17} aria-hidden="true" />
            {deleting ? t('settingsDelete.deleting') : t('settingsDelete.submit')}
          </button>
        </footer>
      </form>
    </div>
  )
}
