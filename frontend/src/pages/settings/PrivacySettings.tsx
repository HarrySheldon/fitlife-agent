import { ArrowLeft, CheckCircle2, ChevronRight, Database, Download, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { api } from '../../services/api'

type Feedback = { kind: 'success' | 'error'; message: string }

export function PrivacySettings() {
  const { t } = useTranslation()
  const [exporting, setExporting] = useState(false)
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const feedbackRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    feedbackRef.current?.focus()
  }, [feedback])

  async function downloadExport() {
    setExporting(true)
    setFeedback(null)
    try {
      const { blob, filename } = await api.exportAccountData()
      const objectUrl = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      try {
        anchor.href = objectUrl
        anchor.download = filename
        anchor.hidden = true
        document.body.appendChild(anchor)
        anchor.click()
      } finally {
        anchor.remove()
        URL.revokeObjectURL(objectUrl)
      }
      setFeedback({ kind: 'success', message: t('settingsPrivacy.exported') })
    } catch (error) {
      setFeedback({ kind: 'error', message: error instanceof Error ? error.message : t('settingsPrivacy.exportFailed') })
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="page-stack settings-page">
      <header className="settings-task-header">
        <Link className="icon-button" to="/settings" aria-label={t('common.back')}>
          <ArrowLeft size={19} />
        </Link>
        <div className="page-header">
          <span>{t('settings.title')}</span>
          <h1>{t('settingsPrivacy.title')}</h1>
        </div>
      </header>

      <div className="settings-form" aria-busy={exporting}>
        <section className="settings-section">
          <div className="settings-section-heading">
            <Database size={19} />
            <h2>{t('settingsPrivacy.exportTitle')}</h2>
            <p>{t('settingsPrivacy.exportDescription')}</p>
          </div>
          <div className="settings-section-control">
            <button className="primary-button" type="button" disabled={exporting} onClick={() => void downloadExport()}>
              <Download size={17} aria-hidden="true" />
              {exporting ? t('settingsPrivacy.exporting') : t('settingsPrivacy.export')}
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

      <nav className="settings-list" aria-label={t('settingsPrivacy.accountActions')}>
        <Link className="settings-row" to="/settings/privacy/delete">
          <span className="settings-row-icon" aria-hidden="true"><Trash2 size={20} /></span>
          <span className="settings-row-copy">
            <strong>{t('settingsPrivacy.deleteTitle')}</strong>
            <span>{t('settingsPrivacy.deleteDescription')}</span>
          </span>
          <ChevronRight size={20} aria-hidden="true" />
        </Link>
      </nav>
    </div>
  )
}
