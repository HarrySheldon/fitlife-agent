import type { GeneratedPlan } from '../types'

export function PlanCard({ plan }: { plan: GeneratedPlan }) {
  return (
    <section className="content-panel">
      <h2>Next Week Plan</h2>
      <div className="split-grid">
        <pre>{JSON.stringify(plan.diet_plan, null, 2)}</pre>
        <pre>{JSON.stringify(plan.workout_plan, null, 2)}</pre>
      </div>
      <h3>Validation</h3>
      <p>{plan.validation.passed ? 'Passed' : 'Needs review'}</p>
      <ul>
        {[...plan.validation.warnings, ...plan.validation.violations].map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  )
}
