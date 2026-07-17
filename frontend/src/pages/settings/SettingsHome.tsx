import { ChevronRight, Cpu, Database, Shield, SlidersHorizontal } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

export function SettingsHome() {
  const { t } = useTranslation()
  return (
    <div className="page-stack settings-page">
      <header className="page-header">
        <span>{t('settings.title')}</span>
        <h1>{t('settings.title')}</h1>
      </header>

      <nav className="settings-list" aria-label={t('settings.tasks')}>
        <Link className="settings-row" to="/settings/general">
          <span className="settings-row-icon" aria-hidden="true"><SlidersHorizontal size={20} /></span>
          <span className="settings-row-copy"><strong>{t('settings.general')}</strong><span>{t('settingsGeneral.description')}</span></span>
          <ChevronRight size={20} aria-hidden="true" />
        </Link>
        <Link className="settings-row" to="/settings/model">
          <span className="settings-row-icon" aria-hidden="true"><Cpu size={20} /></span>
          <span className="settings-row-copy">
            <strong>{t('settings.model')}</strong>
            <span>{t('settings.modelDescription')}</span>
          </span>
          <ChevronRight size={20} aria-hidden="true" />
        </Link>
        <Link className="settings-row" to="/settings/security">
          <span className="settings-row-icon" aria-hidden="true"><Shield size={20} /></span>
          <span className="settings-row-copy">
            <strong>{t('settings.security')}</strong>
            <span>{t('settings.securityDescription')}</span>
          </span>
          <ChevronRight size={20} aria-hidden="true" />
        </Link>
        <Link className="settings-row" to="/settings/privacy">
          <span className="settings-row-icon" aria-hidden="true"><Database size={20} /></span>
          <span className="settings-row-copy">
            <strong>{t('settings.privacy')}</strong>
            <span>{t('settings.privacyDescription')}</span>
          </span>
          <ChevronRight size={20} aria-hidden="true" />
        </Link>
      </nav>
    </div>
  )
}
