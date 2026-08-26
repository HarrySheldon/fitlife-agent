import { Dumbbell, Sparkles, Utensils } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useParams } from 'react-router-dom'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { LoadingState } from '../../components/LoadingState'
import { displayWeight, weightUnit } from '../../domain/units'
import { usePreferences } from '../../hooks/usePreferences'
import { api } from '../../services/api'
import type { DailyDetail } from '../../types'

export function LogbookDay() {
  const { date } = useParams()
  const { t } = useTranslation()
  const { preferences } = usePreferences()
  const [request, setRequest] = useState<{
    date: string
    detail: DailyDetail | null
    error: string | null
    loading: boolean
  } | null>(null)
  const validDate = date && isValidDate(date) ? date : null
  useEffect(() => {
    if (!validDate) return
    let cancelled = false
    setRequest({ date: validDate, detail: null, error: null, loading: true })
    api.calendarDay(validDate).then((result) => {
      if (!cancelled) setRequest({ date: validDate, detail: result, error: null, loading: false })
    }).catch((cause: Error) => {
      if (!cancelled) setRequest({ date: validDate, detail: null, error: cause.message, loading: false })
    })
    return () => { cancelled = true }
  }, [validDate])
  if (!validDate) return <Navigate to="/logbook" replace />
  const current = request?.date === validDate
    ? request
    : { detail: null, error: null, loading: true }
  const { detail, error, loading } = current
  const dateQuery = new URLSearchParams({ date: validDate }).toString()
  return <div className="page-stack logbook-page">
    <header className="page-header inline-header"><div><span>{t('logbook.eyebrow')}</span><h1>{validDate}</h1></div><Link className="secondary-button" to="/logbook">{t('logbook.title')}</Link></header>
    <nav className="button-row" aria-label={t('logbook.actions')}>
      <Link className="primary-button" to={`/today/meal/new?${dateQuery}`}><Utensils size={16} /> {t('logbook.addMeal', { date: validDate })}</Link>
      <Link className="primary-button" to={`/today/workout/new?${dateQuery}`}><Dumbbell size={16} /> {t('logbook.addTraining', { date: validDate })}</Link>
      <Link className="secondary-button" to={`/today/smart-entry?${dateQuery}`}><Sparkles size={16} /> {t('logbook.smartEntry')}</Link>
    </nav>
    {error ? <ErrorState message={error} /> : null}{loading ? <LoadingState label={t('logbook.loading')} /> : null}
    <div className="daily-log-grid">
      <section className="daily-log-section"><header><Utensils size={18} /><h2>{t('logbook.meals')}</h2><span>{detail?.meals.length ?? 0}</span></header>
        <div className="record-list">{detail?.meals.length ? detail.meals.map((row, index) => <div className="record-row" key={`${row.meal}-${row.food}-${index}`}><Utensils size={16} /><span>{row.meal}</span><strong>{row.food}</strong><small>{row.calories} kcal · {row.protein} {t('common.proteinUnit')}</small></div>) : <EmptyState label={t('logbook.noMeals')} />}</div>
      </section>
      <section className="daily-log-section"><header><Dumbbell size={18} /><h2>{t('logbook.training')}</h2><span>{detail?.workouts.length ?? 0}</span></header>
        <div className="record-list">{detail?.workouts.length ? detail.workouts.map((row, index) => <div className="record-row" key={`${row.exercise}-${index}`}><Dumbbell size={16} /><span>{row.type}</span><strong>{row.exercise}</strong><small>{row.duration_min} {t('common.minutesShort')} · {row.muscle_group}{row.weight ? ` · ${displayWeight(row.weight, preferences.unit_system)} ${weightUnit(preferences.unit_system)}` : ''}</small></div>) : <EmptyState label={t('logbook.noTraining')} />}</div>
      </section>
    </div>
  </div>
}

function isValidDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  if (value.startsWith('0000-')) return false
  const parsed = new Date(`${value}T00:00:00.000Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}
