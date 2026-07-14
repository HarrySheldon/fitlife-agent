import { ChevronRight, Cpu, SlidersHorizontal } from 'lucide-react'
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

      <nav className="settings-list" aria-label="Settings tasks">
        <Link className="settings-row" to="/settings/general">
          <span className="settings-row-icon" aria-hidden="true"><SlidersHorizontal size={20} /></span>
          <span className="settings-row-copy"><strong>{t('settings.general')}</strong><span>{t('settingsGeneral.description')}</span></span>
          <ChevronRight size={20} aria-hidden="true" />
        </Link>
        <Link className="settings-row" to="/settings/model">
          <span className="settings-row-icon" aria-hidden="true"><Cpu size={20} /></span>
          <span className="settings-row-copy">
            <strong>{t('settings.model')}</strong>
            <span>Provider, protocol, model and API key</span>
          </span>
          <ChevronRight size={20} aria-hidden="true" />
        </Link>
      </nav>
    </div>
  )
}
