import { ArrowLeft, CheckCircle2, MonitorSmartphone, ShieldCheck } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { useAuth } from '../../hooks/useAuth'
import { api } from '../../services/api'

type Feedback = { kind: 'success' | 'error'; message: string }

export function SessionSettings() {
  const { t } = useTranslation()
  const { replaceSession } = useAuth()
  const [revoking, setRevoking] = useState(false)
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const feedbackRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    feedbackRef.current?.focus()
  }, [feedback])

  async function revoke() {
    setRevoking(true)
    setFeedback(null)
    try {
      const session = await api.revokeOtherSessions()
      replaceSession(session)
      setFeedback({ kind: 'success', message: t('settingsSessions.revoked') })
    } catch (error) {
      setFeedback({ kind: 'error', message: error instanceof Error ? error.message : t('settingsSessions.failed') })
    } finally {
      setRevoking(false)
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
          <h1>{t('settingsSessions.title')}</h1>
        </div>
      </header>

      <div className="settings-form" aria-busy={revoking}>
        <section className="settings-section">
          <div className="settings-section-heading">
            <MonitorSmartphone size={19} />
            <h2>{t('settingsSessions.otherDevices')}</h2>
            <p>{t('settingsSessions.description')}</p>
          </div>
          <div className="settings-section-control">
            <div className="settings-note">
              <ShieldCheck size={18} aria-hidden="true" />
              <span>{t('settingsSessions.currentDevice')}</span>
            </div>
            <button className="primary-button" type="button" disabled={revoking} onClick={() => void revoke()}>
              <MonitorSmartphone size={17} aria-hidden="true" />
              {revoking ? t('settingsSessions.revoking') : t('settingsSessions.submit')}
            </button>
          </div>
        </section>

        {feedback ? (
          <div ref={feedbackRef} className={`settings-feedback ${feedback.kind}`} role={feedback.kind === 'error' ? 'alert' : 'status'} tabIndex={-1}>
            {feedback.kind === 'success' ? <CheckCircle2 size={18} aria-hidden="true" /> : null}
            {feedback.message}
          </div>
        ) : null}
      </div>
    </div>
  )
}
