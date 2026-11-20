import { Bot, Dumbbell, Flame, Scale, Target, TrendingDown, TrendingUp } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { BodyMeasurementModal } from '../components/BodyMeasurementModal'
import { ChartCard } from '../components/ChartCard'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { WeeklyAutomationBanner } from '../components/WeeklyAutomationBanner'
import { usePreferences } from '../hooks/usePreferences'
import { api } from '../services/api'
import { progressApi, type ProgressOverview } from '../services/progressApi'
import type { StoredWeeklyReport } from '../types'

type RangeOption = 30 | 90 | 365
type StrengthMetric = 'estimated_1rm_kg' | 'max_weight_kg' | 'total_volume_kg'

export function Progress() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { localDate } = usePreferences()
  const [rangeDays, setRangeDays] = useState<RangeOption>(30)
  const [data, setData] = useState<ProgressOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reports, setReports] = useState<StoredWeeklyReport[]>([])
  const [reportsLoading, setReportsLoading] = useState(true)
  const [showBodyFat, setShowBodyFat] = useState(false)
  const [showWaist, setShowWaist] = useState(false)
  const [selectedExerciseKey, setSelectedExerciseKey] = useState<string>('')
  const [strengthMetric, setStrengthMetric] = useState<StrengthMetric>('estimated_1rm_kg')
  const [metricModalOpen, setMetricModalOpen] = useState(false)

  const loadOverview = useCallback((days: RangeOption) => {
    let active = true
    setLoading(true)
    setError(null)
    progressApi
      .getProgressOverview(days)
      .then((overview) => {
        if (!active) return
        setData(overview)
        if (overview.exercises.length) {
          setSelectedExerciseKey((prev) =>
            overview.exercises.some((ex) => ex.exercise_key === prev)
              ? prev
              : overview.exercises[0].exercise_key,
          )
        }
      })
      .catch((cause) => {
        if (active) setError(cause instanceof Error ? cause.message : t('common.loadingData'))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [t])

  useEffect(() => loadOverview(rangeDays), [loadOverview, rangeDays])

  useEffect(() => {
    let active = true
    setReportsLoading(true)
    api
      .listWeeklyReports()
      .then((items) => {
        if (active) setReports(items)
      })
      .catch(() => {
        // Keep history empty if unavailable
      })
      .finally(() => {
        if (active) setReportsLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  const activeExercise = useMemo(() => {
    if (!data?.exercises.length) return null
    return data.exercises.find((item) => item.exercise_key === selectedExerciseKey) ?? data.exercises[0]
  }, [data?.exercises, selectedExerciseKey])

  function askCoachAboutProgress(prompt: string) {
    const params = new URLSearchParams({
      surface: 'progress',
      prompt,
    })
    navigate(`/coach?${params.toString()}`)
  }

  return (
    <div className="page-stack progress-page">
      <header className="page-header inline-header">
        <div>
          <span>{t('progress.eyebrow')}</span>
          <h1>{t('progress.title')}</h1>
        </div>
        <div className="progress-toolbar">
          <div className="segmented-control" role="group" aria-label={t('progress.rangeLabel')}>
            {([30, 90, 365] as const).map((days) => (
              <button
                key={days}
                type="button"
                className={rangeDays === days ? 'active' : ''}
                onClick={() => setRangeDays(days)}
              >
                {t(`progress.ranges.d${days}`)}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="primary-button"
            onClick={() => setMetricModalOpen(true)}
          >
            <Scale size={16} />
            {t('bodyMetrics.logAction')}
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={() => askCoachAboutProgress(t('progress.askCoachPrompt'))}
          >
            <Bot size={16} />
            {t('progress.askCoach')}
          </button>
        </div>
      </header>

      <WeeklyAutomationBanner />

      {error ? <ErrorState message={error} /> : null}
      {loading && !data ? <LoadingState label={t('progress.loading')} /> : null}

      {data ? (
        <>
          <section className="progress-kpi-grid" aria-label={t('progress.kpiLabel')}>
            <article className="kpi-card">
              <div className="kpi-head">
                <Scale size={17} />
                <span>{t('progress.kpiWeight')}</span>
              </div>
              <strong className="kpi-value">
                {data.kpis.latest_weight_kg != null
                  ? t('progress.kgValue', { value: data.kpis.latest_weight_kg })
                  : t('progress.noDataShort')}
              </strong>
              <p className="kpi-sub">
                {data.kpis.latest_7d_avg_kg != null
                  ? t('progress.avg7d', { value: data.kpis.latest_7d_avg_kg })
                  : t('progress.needMoreWeight')}
                {data.kpis.weekly_rate_kg != null ? (
                  <span className="kpi-rate">
                    {' · '}
                    {data.kpis.weekly_rate_kg <= 0 ? <TrendingDown size={13} /> : <TrendingUp size={13} />}
                    {t('progress.rateValue', {
                      value: data.kpis.weekly_rate_kg > 0 ? `+${data.kpis.weekly_rate_kg}` : data.kpis.weekly_rate_kg,
                    })}
                  </span>
                ) : null}
              </p>
            </article>

            <article className="kpi-card">
              <div className="kpi-head">
                <Target size={17} />
                <span>{t('progress.kpiAdherence')}</span>
              </div>
              <strong className="kpi-value">
                {data.kpis.adherence_completed} / {data.kpis.adherence_planned}
                <small> ({data.kpis.adherence_pct}%)</small>
              </strong>
              <div className="kpi-bar" aria-hidden="true">
                <span style={{ width: `${Math.min(100, data.kpis.adherence_pct)}%` }} />
              </div>
              <p className="kpi-sub">
                {data.kpis.adherence_mode === 'plan_cycle'
                  ? t('progress.adherenceFromPlan')
                  : t('progress.adherenceFromWeeklyTarget')}
              </p>
            </article>

            <article className="kpi-card">
              <div className="kpi-head">
                <Flame size={17} />
                <span>{t('progress.kpiCalories7d')}</span>
              </div>
              <strong className="kpi-value">
                {data.kpis.calorie_hit_days_7d} / 7 {t('progress.daysUnit')}
              </strong>
              <p className="kpi-sub">
                {t('progress.targetLabel')}: {Math.round(data.kpis.daily_calorie_target)} kcal
              </p>
            </article>

            <article className="kpi-card">
              <div className="kpi-head">
                <Dumbbell size={17} />
                <span>{t('progress.kpiProtein7d')}</span>
              </div>
              <strong className="kpi-value">
                {data.kpis.protein_hit_days_7d} / 7 {t('progress.daysUnit')}
              </strong>
              <p className="kpi-sub">
                {t('progress.targetLabel')}: {Math.round(data.kpis.daily_protein_target)} g
              </p>
            </article>
          </section>

          <section className="progress-main-grid">
            <article className="panel-card progress-chart-panel">
              <header className="section-card-header inline-between">
                <div>
                  <h2>{t('progress.bodyTrendTitle')}</h2>
                  <p className="muted-copy">
                    {data.kpis.target_weight_kg != null
                      ? t('progress.targetWeightNote', { value: data.kpis.target_weight_kg })
                      : t('progress.bodyTrendHint')}
                  </p>
                </div>
                <div className="overlay-toggles">
                  <label>
                    <input
                      type="checkbox"
                      checked={showBodyFat}
                      onChange={(e) => setShowBodyFat(e.target.checked)}
                    />
                    {t('bodyMetrics.bodyFatShort')}
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={showWaist}
                      onChange={(e) => setShowWaist(e.target.checked)}
                    />
                    {t('bodyMetrics.waistShort')}
                  </label>
                </div>
              </header>

              {data.body_summary.trend.length ? (
                <div className="chart-area tall">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={data.body_summary.trend}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2d9cb" />
                      <XAxis dataKey="date" tickFormatter={(v: string) => v.slice(5)} />
                      <YAxis yAxisId="weight" domain={['auto', 'auto']} width={44} />
                      {(showBodyFat || showWaist) ? (
                        <YAxis yAxisId="secondary" orientation="right" domain={['auto', 'auto']} width={40} />
                      ) : null}
                      <Tooltip />
                      <Legend />
                      {data.kpis.target_weight_kg != null ? (
                        <ReferenceLine
                          yAxisId="weight"
                          y={data.kpis.target_weight_kg}
                          stroke="#8f5c38"
                          strokeDasharray="4 4"
                          label={{ value: t('progress.kgValue', { value: data.kpis.target_weight_kg }), fill: '#8f5c38', fontSize: 11 }}
                        />
                      ) : null}
                      <Line
                        yAxisId="weight"
                        type="monotone"
                        dataKey="weight_kg"
                        name={t('bodyMetrics.weightKg')}
                        stroke="#216869"
                        strokeWidth={2}
                        dot={{ r: 3 }}
                        connectNulls
                      />
                      <Line
                        yAxisId="weight"
                        type="monotone"
                        dataKey="moving_avg_7d"
                        name={t('progress.movingAvg7d')}
                        stroke="#d7b377"
                        strokeWidth={3}
                        dot={false}
                        connectNulls
                      />
                      {showBodyFat ? (
                        <Line
                          yAxisId="secondary"
                          type="monotone"
                          dataKey="body_fat_pct"
                          name={t('bodyMetrics.bodyFatShort')}
                          stroke="#49a078"
                          strokeWidth={2}
                          dot={{ r: 2 }}
                          connectNulls
                        />
                      ) : null}
                      {showWaist ? (
                        <Line
                          yAxisId="secondary"
                          type="monotone"
                          dataKey="waist_cm"
                          name={t('bodyMetrics.waistShort')}
                          stroke="#8f5c38"
                          strokeWidth={2}
                          dot={{ r: 2 }}
                          connectNulls
                        />
                      ) : null}
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="cold-start-box">
                  <p>{t('progress.bodyColdStart')}</p>
                  <button type="button" className="secondary-button" onClick={() => setMetricModalOpen(true)}>
                    <Scale size={15} />
                    {t('bodyMetrics.logFirst')}
                  </button>
                </div>
              )}
            </article>

            <article className="panel-card progress-chart-panel">
              <header className="section-card-header inline-between">
                <div>
                  <h2>{t('progress.strengthTitle')}</h2>
                  <p className="muted-copy">{t('progress.strengthHint')}</p>
                </div>
                {data.exercises.length ? (
                  <div className="strength-controls">
                    <select
                      aria-label={t('progress.selectExercise')}
                      value={activeExercise?.exercise_key ?? ''}
                      onChange={(e) => setSelectedExerciseKey(e.target.value)}
                    >
                      {data.exercises.map((ex) => (
                        <option key={ex.exercise_key} value={ex.exercise_key}>
                          {ex.exercise_name} ({ex.session_count})
                        </option>
                      ))}
                    </select>
                    <select
                      aria-label={t('progress.selectMetric')}
                      value={strengthMetric}
                      onChange={(e) => setStrengthMetric(e.target.value as StrengthMetric)}
                    >
                      <option value="estimated_1rm_kg">{t('progress.metrics.e1rm')}</option>
                      <option value="max_weight_kg">{t('progress.metrics.maxWeight')}</option>
                      <option value="total_volume_kg">{t('progress.metrics.volume')}</option>
                    </select>
                  </div>
                ) : null}
              </header>

              {activeExercise ? (
                <>
                  <div className="pr-badges">
                    <span>
                      {t('progress.prBest1rm')}:{' '}
                      <strong>
                        {activeExercise.best_1rm_kg != null
                          ? t('progress.kgValue', { value: activeExercise.best_1rm_kg })
                          : '—'}
                      </strong>
                    </span>
                    <span>
                      {t('progress.prBestWeight')}:{' '}
                      <strong>
                        {activeExercise.best_weight_kg != null
                          ? t('progress.kgValue', { value: activeExercise.best_weight_kg })
                          : '—'}
                      </strong>
                    </span>
                    <span>
                      {t('progress.prBestVolume')}:{' '}
                      <strong>{t('progress.kgValue', { value: Math.round(activeExercise.best_volume_kg) })}</strong>
                    </span>
                  </div>
                  <div className="chart-area tall">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={activeExercise.series}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2d9cb" />
                        <XAxis dataKey="date" tickFormatter={(v: string) => v.slice(5)} />
                        <YAxis domain={['auto', 'auto']} width={44} />
                        <Tooltip />
                        <Line
                          type="monotone"
                          dataKey={strengthMetric}
                          stroke="#216869"
                          strokeWidth={3}
                          dot={{ r: 4 }}
                          connectNulls
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="pr-table-wrap">
                    <table className="pr-table">
                      <thead>
                        <tr>
                          <th>{t('progress.colExercise')}</th>
                          <th>{t('progress.colSessions')}</th>
                          <th>{t('progress.colBestWeight')}</th>
                          <th>{t('progress.colBest1rm')}</th>
                          <th>{t('progress.colDelta')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.exercises.slice(0, 6).map((ex) => (
                          <tr
                            key={ex.exercise_key}
                            className={ex.exercise_key === activeExercise.exercise_key ? 'active-row' : ''}
                            onClick={() => setSelectedExerciseKey(ex.exercise_key)}
                          >
                            <td>{ex.exercise_name}</td>
                            <td>{ex.session_count}</td>
                            <td>{ex.best_weight_kg != null ? t('progress.kgValue', { value: ex.best_weight_kg }) : '—'}</td>
                            <td>{ex.best_1rm_kg != null ? t('progress.kgValue', { value: ex.best_1rm_kg }) : '—'}</td>
                            <td>
                              {ex.delta_1rm_kg != null
                                ? t('progress.kgValue', {
                                  value: `${ex.delta_1rm_kg > 0 ? '+' : ''}${ex.delta_1rm_kg}`,
                                })
                                : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <div className="cold-start-box">
                  <p>{t('progress.strengthColdStart')}</p>
                  <Link className="secondary-button" to="/today/workout/new">
                    <Dumbbell size={15} />
                    {t('today.addTraining')}
                  </Link>
                </div>
              )}
            </article>
          </section>

          <section className="chart-grid" aria-label={t('review.trends')}>
            <ChartCard
              title={t('review.calorieTrend')}
              data={data.calorie_trend}
              referenceValue={data.kpis.daily_calorie_target}
              referenceLabel={`${Math.round(data.kpis.daily_calorie_target)} kcal`}
            />
            <ChartCard
              title={t('review.proteinTrend')}
              data={data.protein_trend}
              referenceValue={data.kpis.daily_protein_target}
              referenceLabel={`${Math.round(data.kpis.daily_protein_target)} g`}
            />
            <ChartCard title={t('review.workoutCount')} data={data.workout_count_trend} />
            <ChartCard title={t('review.macroSplit')} data={data.macro_distribution} type="pie" />
          </section>

          <section className="history-panel">
            <h2>{t('review.history')}</h2>
            {reportsLoading ? <LoadingState label={t('review.loadingHistory')} /> : null}
            {!reportsLoading && reports.length === 0 ? <EmptyState label={t('review.noHistory')} /> : null}
            {reports.length ? (
              <div className="history-list">
                {reports.map((item) => (
                  <div className="history-row progress-report-row" key={item.week}>
                    <Link to={`/progress/week/${item.week}`}>
                      <strong>{item.week}</strong>
                      <span> · {item.report.title}</span>
                    </Link>
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() =>
                        askCoachAboutProgress(t('progress.interpretWeekPrompt', { week: item.week }))
                      }
                    >
                      <Bot size={15} />
                      {t('review.explain')}
                    </button>
                  </div>
                ))}
              </div>
            ) : null}
          </section>
        </>
      ) : null}

      <BodyMeasurementModal
        open={metricModalOpen}
        defaultDate={localDate()}
        onClose={() => setMetricModalOpen(false)}
        onSaved={() => {
          loadOverview(rangeDays)
        }}
      />
    </div>
  )
}
