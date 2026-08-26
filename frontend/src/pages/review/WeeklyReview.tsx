import { Bot, FileText } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'

import { CoachDrawer } from '../../components/CoachDrawer'
import { ErrorState } from '../../components/ErrorState'
import { LoadingState } from '../../components/LoadingState'
import { ReportViewer } from '../../components/ReportViewer'
import { api } from '../../services/api'
import type { CoachActionResponse, StoredWeeklyReport } from '../../types'

export function WeeklyReview() {
  const { t } = useTranslation()
  const { week = '' } = useParams()
  const validWeek = isIsoWeekKey(week)
  const routeWeekRef = useRef(week)
  const requestGenerationRef = useRef(0)
  const activeOperationRef = useRef<{ kind: 'generating' | 'interpreting'; owner: symbol } | null>(null)
  if (routeWeekRef.current !== week) {
    routeWeekRef.current = week
    requestGenerationRef.current += 1
    activeOperationRef.current = null
  }
  const [stored, setStored] = useState<StoredWeeklyReport | null>(null)
  const [loading, setLoading] = useState(validWeek)
  const [generating, setGenerating] = useState(false)
  const [interpreting, setInterpreting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [coachOpen, setCoachOpen] = useState(false)
  const coachTriggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const requestGeneration = ++requestGenerationRef.current
    if (!validWeek) {
      setStored(null); setLoading(false); setError(t('review.invalidWeek')); return
    }
    setStored(null); setLoading(true); setError(null)
    activeOperationRef.current = null
    setGenerating(false); setInterpreting(false); setCoachOpen(false)
    api.getWeeklyReport(week).then((report) => {
      if (requestGenerationRef.current === requestGeneration) setStored(report)
    })
      .catch((err) => {
        if (requestGenerationRef.current === requestGeneration) setError((err as Error).message)
      })
      .finally(() => {
        if (requestGenerationRef.current === requestGeneration) setLoading(false)
      })
    return () => {
      if (requestGenerationRef.current === requestGeneration) requestGenerationRef.current += 1
    }
  }, [t, validWeek, week])

  async function generate() {
    if (!validWeek) return
    const owner = beginOperation('generating')
    if (!owner) return
    const requestGeneration = ++requestGenerationRef.current
    setLoading(false); setGenerating(true); setError(null)
    setCoachOpen(false)
    try {
      const report = await api.generateWeeklyReport(week)
      if (requestGenerationRef.current === requestGeneration) setStored(report)
    }
    catch (err) {
      if (requestGenerationRef.current === requestGeneration) setError((err as Error).message)
    }
    finally {
      if (requestGenerationRef.current === requestGeneration) finishOperation(owner)
    }
  }

  async function interpret(): Promise<CoachActionResponse> {
    if (!validWeek || !stored) throw new Error('WEEKLY_REPORT_REQUIRED')
    const owner = beginOperation('interpreting')
    if (!owner) throw new Error('WEEKLY_REPORT_OPERATION_IN_PROGRESS')
    const requestGeneration = ++requestGenerationRef.current
    setInterpreting(true)
    try {
      return await api.interpretWeeklyReport(week)
    } finally {
      if (requestGenerationRef.current === requestGeneration) finishOperation(owner)
    }
  }

  function beginOperation(kind: 'generating' | 'interpreting'): symbol | null {
    if (activeOperationRef.current) return null
    const owner = Symbol(kind)
    activeOperationRef.current = { kind, owner }
    return owner
  }

  function finishOperation(owner: symbol) {
    const operation = activeOperationRef.current
    if (operation?.owner !== owner) return
    activeOperationRef.current = null
    if (operation.kind === 'generating') setGenerating(false)
    else setInterpreting(false)
  }

  return <div className="page-stack review-page">
    <Link className="text-link" to="/review">← {t('review.back')}</Link>
    <header className="page-header inline-header">
      <div><span>{t('review.detailEyebrow')}</span><h1>{week}</h1></div>
      {validWeek ? <button className="primary-button" type="button" onClick={() => void generate()} disabled={generating || interpreting}><FileText size={17} />{generating ? t('common.generating') : t('review.generate')}</button> : null}
    </header>
    {error ? <ErrorState message={error} /> : null}
    {loading ? <LoadingState label={t('review.loadingReport')} /> : null}
    {stored ? <div className="review-layout"><div className="review-main"><ReportViewer report={stored.report} /></div><button ref={coachTriggerRef} className="secondary-button coach-trigger" type="button" disabled={generating} onClick={() => { if (activeOperationRef.current?.kind !== 'generating') setCoachOpen(true) }}><Bot size={17} />{t('coach.open')}</button></div> : null}
    <CoachDrawer open={coachOpen} onClose={() => setCoachOpen(false)} returnFocusRef={coachTriggerRef} surface="review" question={`ISO week: ${week}`} requestAction={interpret} actionsDisabled={generating || interpreting} actions={[{ action: 'explain_weekly_report', label: t('review.explain') }]} />
  </div>
}

function isIsoWeekKey(value: string): boolean {
  const match = /^(\d{4})-W(\d{2})$/.exec(value)
  if (!match) return false
  const year = Number(match[1]); const week = Number(match[2])
  if (week < 1 || week > 53) return false
  const jan4 = new Date(Date.UTC(year, 0, 4)); const firstMonday = new Date(jan4)
  firstMonday.setUTCDate(jan4.getUTCDate() - ((jan4.getUTCDay() + 6) % 7))
  const thursday = new Date(firstMonday); thursday.setUTCDate(firstMonday.getUTCDate() + (week - 1) * 7 + 3)
  return thursday.getUTCFullYear() === year
}
