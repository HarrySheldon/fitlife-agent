import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { ReportViewer } from '../components/ReportViewer'
import { api } from '../services/api'
import type { WeeklyReport as WeeklyReportType } from '../types'

export function WeeklyReport() {
  const { t } = useTranslation()
  const [report, setReport] = useState<WeeklyReportType | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function generate() {
    setLoading(true)
    setError(null)
    try {
      setReport(await api.weeklyReport())
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page-stack">
      <header className="page-header inline-header">
        <div>
          <span>{t('legacy.reportEyebrow')}</span>
          <h1>{t('legacy.reportTitle')}</h1>
        </div>
        <button className="primary-button" type="button" onClick={() => void generate()}>{loading ? t('common.generating') : t('legacy.generateReport')}</button>
      </header>
      {error ? <ErrorState message={error} /> : null}
      {report ? <ReportViewer report={report} /> : <EmptyState label={t('legacy.noReport')} />}
    </div>
  )
}
