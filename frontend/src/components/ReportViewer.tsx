import type { WeeklyReport } from '../types'
import { useTranslation } from 'react-i18next'

export function ReportViewer({ report }: { report: WeeklyReport }) {
  const { t } = useTranslation()
  return (
    <section className="content-panel">
      <h2>{report.title}</h2>
      {report.sections.map((section) => (
        <article key={section.title} className="section-block">
          <h3>{section.title}</h3>
          <p>{section.content}</p>
        </article>
      ))}
      <h3>{t('components.checklist')}</h3>
      <ul>{report.checklist.map((item) => <li key={item}>{item}</li>)}</ul>
    </section>
  )
}
