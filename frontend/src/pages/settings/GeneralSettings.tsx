import { ArrowLeft, Clock3, Languages, Ruler } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { ErrorState } from '../../components/ErrorState'
import { LoadingState } from '../../components/LoadingState'
import { usePreferences } from '../../hooks/usePreferences'
import type { AppLanguage, UnitSystem } from '../../types'

const FALLBACK_TIMEZONES = ['UTC', 'Asia/Shanghai', 'Asia/Tokyo', 'Asia/Singapore', 'Europe/London', 'Europe/Berlin', 'America/New_York', 'America/Chicago', 'America/Los_Angeles', 'Australia/Sydney']

export function GeneralSettings() {
  const { t } = useTranslation()
  const { preferences, loading, error, updatePreferences } = usePreferences()
  if (loading) return <LoadingState label={t('settingsGeneral.loading')} />

  const chooseLanguage = (language: AppLanguage) => void updatePreferences({ language })
  const chooseUnit = (unit_system: UnitSystem) => void updatePreferences({ unit_system })

  return (
    <div className="page-stack settings-page">
      <header className="settings-task-header">
        <Link className="icon-button" to="/settings" aria-label={t('common.back')}><ArrowLeft size={19} /></Link>
        <div className="page-header"><span>{t('settings.title')}</span><h1>{t('settingsGeneral.title')}</h1></div>
      </header>
      {error ? <ErrorState message={error} /> : null}
      <div className="settings-form">
        <section className="settings-section">
          <div className="settings-section-heading"><Languages size={19} /><h2>{t('settingsGeneral.language')}</h2><p>{t('settingsGeneral.languageDescription')}</p></div>
          <div className="settings-section-control">
            <div className="settings-segmented" aria-label={t('settingsGeneral.language')}>
              <button type="button" className={preferences.language === 'en-US' ? 'active' : ''} onClick={() => chooseLanguage('en-US')}>English</button>
              <button type="button" className={preferences.language === 'zh-CN' ? 'active' : ''} onClick={() => chooseLanguage('zh-CN')}>中文</button>
            </div>
          </div>
        </section>
        <section className="settings-section">
          <div className="settings-section-heading"><Ruler size={19} /><h2>{t('settingsGeneral.units')}</h2><p>{t('settingsGeneral.unitsDescription')}</p></div>
          <div className="settings-section-control unit-choice-list">
            <UnitChoice checked={preferences.unit_system === 'metric'} label={t('settingsGeneral.metric')} example="kg · cm · km" value="metric" onChange={chooseUnit} />
            <UnitChoice checked={preferences.unit_system === 'imperial'} label={t('settingsGeneral.imperial')} example="lb · ft/in · mi" value="imperial" onChange={chooseUnit} />
          </div>
        </section>
        <section className="settings-section">
          <div className="settings-section-heading"><Clock3 size={19} /><h2>{t('settingsGeneral.timezone')}</h2><p>{t('settingsGeneral.timezoneDescription')}</p></div>
          <div className="settings-section-control">
            <label className="settings-field"><span>{t('settingsGeneral.timezone')}</span><select value={preferences.timezone} onChange={(event) => void updatePreferences({ timezone: event.target.value })}>{supportedTimezones(preferences.timezone).map((timezone) => <option key={timezone} value={timezone}>{timezone}</option>)}</select></label>
          </div>
        </section>
      </div>
    </div>
  )
}

function UnitChoice({ checked, label, example, value, onChange }: { checked: boolean; label: string; example: string; value: UnitSystem; onChange: (value: UnitSystem) => void }) {
  return <label className={`unit-choice ${checked ? 'selected' : ''}`}><input type="radio" name="unit-system" value={value} checked={checked} onChange={() => onChange(value)} /><span><strong>{label}</strong><small>{example}</small></span></label>
}

function supportedTimezones(current: string): string[] {
  const timezoneIntl = Intl as typeof Intl & { supportedValuesOf?: (key: 'timeZone') => string[] }
  return Array.from(new Set([current, 'UTC', ...(timezoneIntl.supportedValuesOf?.('timeZone') ?? FALLBACK_TIMEZONES)])).sort()
}

