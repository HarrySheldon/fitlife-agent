import { Sparkles, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useInRouterContext, useLocation } from 'react-router-dom'

import {
  weeklyAutomationApi,
  type WeeklyAutomationRun,
} from '../services/weeklyAutomationApi'

let inflightCheck: Promise<{ run: WeeklyAutomationRun }> | null = null

function runCoalescedCheck(): Promise<{ run: WeeklyAutomationRun }> {
  if (!inflightCheck) {
    inflightCheck = weeklyAutomationApi.check().finally(() => {
      inflightCheck = null
    })
  }
  return inflightCheck
}

export function WeeklyAutomationBanner({
  onDraftGenerated,
}: {
  onDraftGenerated?: () => void
}) {
  const inRouter = useInRouterContext()
  if (inRouter) {
    return <RouterAwareWeeklyAutomationBanner onDraftGenerated={onDraftGenerated} />
  }
  return <WeeklyAutomationBannerBody onDraftGenerated={onDraftGenerated} onPlanPage={false} />
}

function RouterAwareWeeklyAutomationBanner({
  onDraftGenerated,
}: {
  onDraftGenerated?: () => void
}) {
  const location = useLocation()
  return (
    <WeeklyAutomationBannerBody
      onDraftGenerated={onDraftGenerated}
      onPlanPage={location.pathname === '/plan'}
    />
  )
}

function WeeklyAutomationBannerBody({
  onDraftGenerated,
  onPlanPage,
}: {
  onDraftGenerated?: () => void
  onPlanPage: boolean
}) {
  const { t } = useTranslation()
  const [run, setRun] = useState<WeeklyAutomationRun | null>(null)
  const onDraftGeneratedRef = useRef(onDraftGenerated)
  onDraftGeneratedRef.current = onDraftGenerated

  useEffect(() => {
    let active = true
    runCoalescedCheck()
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
        if (
          item &&
          (item.draft_status === 'generated_agent' ||
            item.draft_status === 'generated_deterministic')
        ) {
          onDraftGeneratedRef.current?.()
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
        {run.draft_cycle_id && !onPlanPage ? (
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
