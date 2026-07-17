import { ArrowLeft, ChevronRight, LockKeyhole, MonitorSmartphone } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

export function SecuritySettings() {
  const { t } = useTranslation()

  return (
    <div className="page-stack settings-page">
      <header className="settings-task-header">
        <Link className="icon-button" to="/settings" aria-label={t('common.back')}>
          <ArrowLeft size={19} />
        </Link>
        <div className="page-header">
          <span>{t('settings.title')}</span>
          <h1>{t('settingsSecurity.title')}</h1>
        </div>
      </header>

      <nav className="settings-list" aria-label={t('settingsSecurity.tasks')}>
        <Link className="settings-row" to="/settings/security/password">
          <span className="settings-row-icon" aria-hidden="true"><LockKeyhole size={20} /></span>
          <span className="settings-row-copy">
            <strong>{t('settingsSecurity.password')}</strong>
            <span>{t('settingsSecurity.passwordDescription')}</span>
          </span>
          <ChevronRight size={20} aria-hidden="true" />
        </Link>
        <Link className="settings-row" to="/settings/security/sessions">
          <span className="settings-row-icon" aria-hidden="true"><MonitorSmartphone size={20} /></span>
          <span className="settings-row-copy">
            <strong>{t('settingsSecurity.sessions')}</strong>
            <span>{t('settingsSecurity.sessionsDescription')}</span>
          </span>
          <ChevronRight size={20} aria-hidden="true" />
        </Link>
      </nav>
    </div>
  )
}
