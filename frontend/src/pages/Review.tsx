import { FileText } from 'lucide-react'
import { useState } from 'react'

import { ChartCard } from '../components/ChartCard'
import { CoachPanel } from '../components/CoachPanel'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { ReportViewer } from '../components/ReportViewer'
import { useDashboard } from '../hooks/useDashboard'
import { api } from '../services/api'
import type { WeeklyReport } from '../types'

export function Review() {
  const { data, loading, error } = useDashboard()
  const [report, setReport] = useState<WeeklyReport | null>(null)
  const [reportLoading, setReportLoading] = useState(false)
  const [reportError, setReportError] = useState<string | null>(null)

  async function generateReport() {
    setReportLoading(true)
    setReportError(null)
    try {
      setReport(await api.weeklyReport())
    } catch (err) {
      setReportError((err as Error).message)
    } finally {
      setReportLoading(false)
    }
  }

  return (
    <div className="page-stack review-page">
      <header className="page-header inline-header">
        <div><span>Trends and weekly insight</span><h1>Review</h1></div>
        <button className="primary-button" type="button" onClick={() => void generateReport()} disabled={reportLoading}><FileText size={17} />{reportLoading ? 'Generating...' : 'Generate weekly report'}</button>
      </header>
      {error ? <ErrorState message={error} /> : null}
      {reportError ? <ErrorState message={reportError} /> : null}
      {loading && !data ? <LoadingState label="Loading trends" /> : null}
      {data ? (
        <div className="review-layout">
          <div className="review-main">
            <section className="chart-grid">
              <ChartCard title="Calorie trend" data={data.calorie_trend} />
              <ChartCard title="Protein trend" data={data.protein_trend} />
              <ChartCard title="Workout count" data={data.workout_count_trend} />
              <ChartCard title="Macro split" data={data.macro_distribution} type="pie" />
            </section>
            {report ? <ReportViewer report={report} /> : <EmptyState label="Generate a report when you are ready to review the week" />}
          </div>
          <CoachPanel surface="review" actions={[{ action: 'explain_weekly_report', label: 'Explain weekly patterns' }]} />
        </div>
      ) : null}
    </div>
  )
}
