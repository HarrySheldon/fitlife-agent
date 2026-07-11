import type { GeneratedPlan } from '../types'

export function PlanCard({ plan }: { plan: GeneratedPlan }) {
  return (
    <section className="plan-result">
      <header className={`validation-summary ${plan.validation.passed ? 'passed' : 'review'}`}>
        <div><span>Validation</span><strong>{plan.validation.passed ? 'Ready to use' : 'Needs review'}</strong></div>
        <span>{plan.validation.warnings.length + plan.validation.violations.length} findings</span>
      </header>
      {[...plan.validation.warnings, ...plan.validation.violations].length ? (
        <ul className="validation-findings">
          {[...plan.validation.warnings, ...plan.validation.violations].map((item) => <li key={item}>{item}</li>)}
        </ul>
      ) : null}
      <div className="plan-sections">
        <section><span>Nutrition</span><h2>Diet plan</h2><pre>{JSON.stringify(plan.diet_plan, null, 2)}</pre></section>
        <section><span>Training</span><h2>Workout plan</h2><pre>{JSON.stringify(plan.workout_plan, null, 2)}</pre></section>
      </div>
    </section>
  )
}
