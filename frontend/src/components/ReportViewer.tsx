import type { WeeklyReport } from '../types'

export function ReportViewer({ report }: { report: WeeklyReport }) {
  return (
    <section className="content-panel">
      <h2>{report.title}</h2>
      {report.sections.map((section) => (
        <article key={section.title} className="section-block">
          <h3>{section.title}</h3>
          <p>{section.content}</p>
        </article>
      ))}
      <h3>Checklist</h3>
      <ul>{report.checklist.map((item) => <li key={item}>{item}</li>)}</ul>
    </section>
  )
}
