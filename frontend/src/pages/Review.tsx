import { Link } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ChartCard } from '../components/ChartCard'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { useDashboard } from '../hooks/useDashboard'
import { api } from '../services/api'
import type { StoredWeeklyReport } from '../types'

export function Review() {
  const { t } = useTranslation()
  const { data, loading, error } = useDashboard()
  const [reports, setReports] = useState<StoredWeeklyReport[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    api.listWeeklyReports().then((items) => { if (active) setReports(items) })
      .catch((err) => { if (active) setHistoryError((err as Error).message) })
      .finally(() => { if (active) setHistoryLoading(false) })
    return () => { active = false }
  }, [])

  return (
    <div className="page-stack review-page">
      <header className="page-header">
        <span>{t('review.eyebrow')}</span><h1>{t('review.title')}</h1>
      </header>
      {error ? <ErrorState message={error} /> : null}
      {loading && !data ? <LoadingState label={t('review.loading')} /> : null}
      {data ? (
        <section className="chart-grid" aria-label={t('review.trends')}>
              <ChartCard title={t('review.calorieTrend')} data={data.calorie_trend} />
              <ChartCard title={t('review.proteinTrend')} data={data.protein_trend} />
              <ChartCard title={t('review.workoutCount')} data={data.workout_count_trend} />
              <ChartCard title={t('review.macroSplit')} data={data.macro_distribution} type="pie" />
        </section>
      ) : null}
      <section className="content-panel">
        <h2>{t('review.history')}</h2>
        {historyError ? <ErrorState message={historyError} /> : null}
        {historyLoading ? <LoadingState label={t('review.loadingHistory')} /> : null}
        {!historyLoading && !historyError && reports.length === 0 ? <EmptyState label={t('review.noHistory')} /> : null}
        {reports.length > 0 ? <ul>{reports.map((item) => <li key={item.week}><Link to={`/review/week/${item.week}`}>{item.week} · {item.report.title}</Link></li>)}</ul> : null}
      </section>
    </div>
  )
}
