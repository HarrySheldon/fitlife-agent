import { ChartCard } from '../components/ChartCard'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { MetricCard } from '../components/MetricCard'
import { useDashboard } from '../hooks/useDashboard'
import { useTranslation } from 'react-i18next'

export function Dashboard() {
  const { t } = useTranslation()
  const { data, loading, error } = useDashboard()
  if (loading) return <LoadingState />
  if (error) return <ErrorState message={error} />
  if (!data) return null

  return (
    <div className="page-stack">
      <header className="page-header">
        <span>{t('legacy.dashboardEyebrow')}</span>
        <h1>{t('legacy.dashboardTitle')}</h1>
      </header>
      <div className="metric-grid">
        <MetricCard label={t('legacy.dayCalories')} value={`${data.today_calories} kcal`} detail={data.summary_date} />
        <MetricCard label={t('legacy.dayProtein')} value={`${data.today_protein} g`} detail={data.meal_summary} />
        <MetricCard label={t('legacy.trainingSessions')} value={data.weekly_training_count} detail={t('legacy.currentWindow')} />
        <MetricCard label={t('legacy.trainingDuration')} value={`${data.weekly_training_duration_min} ${t('common.minutesShort')}`} />
      </div>
      <div className="chart-grid">
        <ChartCard title={t('legacy.calorieTrend')} data={data.calorie_trend} />
        <ChartCard title={t('legacy.proteinTrend')} data={data.protein_trend} />
        <ChartCard title={t('legacy.workoutCount')} data={data.workout_count_trend} />
        <ChartCard title={t('legacy.macroSplit')} data={data.macro_distribution} type="pie" />
      </div>
    </div>
  )
}
