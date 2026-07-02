interface MetricCardProps {
  label: string
  value: string | number
  detail?: string
}

export function MetricCard({ label, value, detail }: MetricCardProps) {
  return (
    <section className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <p>{detail}</p> : null}
    </section>
  )
}
