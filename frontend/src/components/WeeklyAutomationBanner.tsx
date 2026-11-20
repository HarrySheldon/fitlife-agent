import { Sparkles, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import {
  weeklyAutomationApi,
  type WeeklyAutomationRun,
} from '../services/weeklyAutomationApi'

export function WeeklyAutomationBanner() {
  const { t } = useTranslation()
  const [run, setRun] = useState<WeeklyAutomationRun | null>(null)

  useEffect(() => {
    let active = true
    weeklyAutomationApi
      .check()
      .then((res) => {
        if (!active) return
        const item = res.run
        if (
          item &&
          !item.dismissed &&
          (item.report_status === 'generated' ||
            item.draft_status === 'generated_agent' ||
            item.draft_status === 'generated_deterministic')
        ) {
          setRun(item)
        }
      })
      .catch(() => {
        // Silent no-op when unauthenticated or offline
      })
    return () => {
      active = false
    }
  }, [])

  if (!run) return null

  async function handleDismiss() {
    if (!run) return
    const week = run.iso_week
    setRun(null)
    try {
      await weeklyAutomationApi.dismiss(week)
    } catch {
      // Already dismissed locally
    }
  }

  return (
    <aside className="weekly-automation-banner" role="status" aria-label={t('weeklyAutomation.label')}>
      <div className="weekly-automation-copy">
        <Sparkles size={16} />
        <span>{run.message}</span>
      </div>
      <div className="weekly-automation-actions">
        {run.report_status === 'generated' ? (
          <Link className="secondary-button" to={`/progress/week/${run.report_week}`}>
            {t('weeklyAutomation.viewReport')}
          </Link>
        ) : null}
        {run.draft_cycle_id ? (
          <Link className="primary-button" to="/plan">
            {t('weeklyAutomation.reviewDraft')}
          </Link>
        ) : null}
        <button
          type="button"
          className="icon-button"
          aria-label={t('weeklyAutomation.dismiss')}
          onClick={() => void handleDismiss()}
        >
          <X size={16} />
        </button>
      </div>
    </aside>
  )
}
