import { CalendarDays, Upload } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { ErrorState } from '../components/ErrorState'
import { FileUploader } from '../components/FileUploader'
import { LoadingState } from '../components/LoadingState'
import { usePreferences } from '../hooks/usePreferences'
import { api } from '../services/api'
import type { DailySummary } from '../types'

export function Logbook() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { localDate } = usePreferences()
  const endDate = localDate()
  const [days, setDays] = useState<DailySummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const range = useMemo(() => dateRange(endDate), [endDate])
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.calendarDays(range.start, range.end).then((result) => { if (!cancelled) setDays(result) })
      .catch((cause: Error) => { if (!cancelled) setError(cause.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [range])
  return <div className="page-stack logbook-page">
    <header className="page-header inline-header"><div><span>{t('logbook.eyebrow')}</span><h1>{t('logbook.title')}</h1></div>
      <label className="date-picker"><CalendarDays size={18} /><input type="date" value={endDate} onChange={(event) => navigate(`/logbook/${event.target.value}`)} /></label>
    </header>
    {error ? <ErrorState message={error} /> : null}{loading ? <LoadingState label={t('logbook.loading')} /> : null}
    <section className="calendar-strip" aria-label={t('logbook.lastDays')}>{days.map((day) =>
      <Link key={day.date} className={`day-tile ${day.has_data ? 'has-data' : ''}`} to={`/logbook/${day.date}`}>
        <span>{day.date.slice(5)}</span><strong>{Math.round(day.calories)}</strong><small>{day.training_sessions} {t('common.trainingShort')}</small>
      </Link>)}</section>
    <Link className="secondary-button" to="/logbook/import"><Upload size={16} /> {t('logbook.csvImport')}</Link>
  </div>
}

export function LogbookImport() {
  const { t } = useTranslation()
  return <div className="page-stack logbook-page">
    <header className="page-header"><span>{t('logbook.optionalInput')}</span><h1>{t('logbook.csvImport')}</h1></header>
    <section className="import-tool">
      <FileUploader label="meals.csv" onUpload={(file) => api.upload('meals', file).then(() => undefined)} />
      <FileUploader label="workouts.csv" onUpload={(file) => api.upload('workouts', file).then(() => undefined)} />
    </section>
  </div>
}

function dateRange(endDate: string) {
  const end = new Date(`${endDate}T00:00:00`)
  const start = new Date(end)
  start.setDate(end.getDate() - 29)
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) }
}
