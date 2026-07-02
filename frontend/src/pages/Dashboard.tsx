import { ChartCard } from '../components/ChartCard'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { MetricCard } from '../components/MetricCard'
import { useDashboard } from '../hooks/useDashboard'

export function Dashboard() {
  const { data, loading, error } = useDashboard()
  if (loading) return <LoadingState />
  if (error) return <ErrorState message={error} />
  if (!data) return null

  return (
    <div className="page-stack">
      <header className="page-header">
        <span>Operational overview</span>
        <h1>Fitness and nutrition control room</h1>
      </header>
      <div className="metric-grid">
        <MetricCard label="Today calories" value={`${data.today_calories} kcal`} detail={data.meal_summary} />
        <MetricCard label="Today protein" value={`${data.today_protein} g`} />
        <MetricCard label="Training sessions" value={data.weekly_training_count} detail="Current data window" />
        <MetricCard label="Training duration" value={`${data.weekly_training_duration_min} min`} />
      </div>
      <div className="chart-grid">
        <ChartCard title="Calorie Trend" data={data.calorie_trend} />
        <ChartCard title="Protein Trend" data={data.protein_trend} />
        <ChartCard title="Workout Count" data={data.workout_count_trend} />
        <ChartCard title="Macro Split" data={data.macro_distribution} type="pie" />
      </div>
    </div>
  )
}
