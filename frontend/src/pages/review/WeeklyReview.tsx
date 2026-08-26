import { Bot, FileText, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'

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
  if (routeWeekRef.current !== week) {
    routeWeekRef.current = week
    requestGenerationRef.current += 1
  }
  const [stored, setStored] = useState<StoredWeeklyReport | null>(null)
  const [loading, setLoading] = useState(validWeek)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [interpretation, setInterpretation] = useState<CoachActionResponse | null>(null)
  const [interpreting, setInterpreting] = useState(false)
  const [interpretationError, setInterpretationError] = useState<string | null>(null)

  useEffect(() => {
    const requestGeneration = ++requestGenerationRef.current
    if (!validWeek) {
      setStored(null); setLoading(false); setError(t('review.invalidWeek')); return
    }
    setStored(null); setLoading(true); setError(null)
    setGenerating(false); setInterpreting(false)
    setInterpretation(null); setInterpretationError(null)
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
    const requestGeneration = ++requestGenerationRef.current
    setLoading(false); setGenerating(true); setError(null)
    setInterpreting(false); setInterpretation(null); setInterpretationError(null)
    try {
      const report = await api.generateWeeklyReport(week)
      if (requestGenerationRef.current === requestGeneration) setStored(report)
    }
    catch (err) {
      if (requestGenerationRef.current === requestGeneration) setError((err as Error).message)
    }
    finally {
      if (requestGenerationRef.current === requestGeneration) setGenerating(false)
    }
  }

  async function interpret() {
    if (!validWeek || !stored) return
    const requestGeneration = ++requestGenerationRef.current
    setInterpreting(true); setInterpretation(null); setInterpretationError(null)
    try {
      const answer = await api.interpretWeeklyReport(week)
      if (requestGenerationRef.current === requestGeneration) setInterpretation(answer)
    }
    catch (err) {
      if (requestGenerationRef.current === requestGeneration) setInterpretationError((err as Error).message)
    }
    finally {
      if (requestGenerationRef.current === requestGeneration) setInterpreting(false)
    }
  }

  return <div className="page-stack review-page">
    <Link className="text-link" to="/review">← {t('review.back')}</Link>
    <header className="page-header inline-header">
      <div><span>{t('review.detailEyebrow')}</span><h1>{week}</h1></div>
      {validWeek ? <button className="primary-button" type="button" onClick={() => void generate()} disabled={generating || interpreting}><FileText size={17} />{generating ? t('common.generating') : t('review.generate')}</button> : null}
    </header>
    {error ? <ErrorState message={error} /> : null}
    {loading ? <LoadingState label={t('review.loadingReport')} /> : null}
    {stored ? <div className="review-layout"><div className="review-main"><ReportViewer report={stored.report} /></div><aside className="coach-panel"><header><Bot size={20} /><div><span>{t('coach.eyebrow')}</span><h2>{t('coach.title')}</h2></div></header><div className="coach-actions"><button type="button" onClick={() => void interpret()} disabled={interpreting || generating}><Sparkles size={16} />{interpreting ? t('coach.thinking') : t('review.explain')}</button></div>{interpretationError ? <p className="form-error">{interpretationError}</p> : null}{interpretation ? <div className="coach-answer"><ReactMarkdown>{interpretation.answer_markdown}</ReactMarkdown></div> : <p className="coach-empty">{t('coach.empty')}</p>}</aside></div> : null}
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
