import type { GeneratedPlan } from '../types'
import { useTranslation } from 'react-i18next'

export function PlanCard({ plan }: { plan: GeneratedPlan }) {
  const { t } = useTranslation()
  return (
    <section className="plan-result">
      <header className={`validation-summary ${plan.validation.passed ? 'passed' : 'review'}`}>
        <div><span>{t('plan.validation')}</span><strong>{plan.validation.passed ? t('plan.ready') : t('plan.needsReview')}</strong></div>
        <span>{plan.validation.warnings.length + plan.validation.violations.length} {t('common.findings')}</span>
      </header>
      {[...plan.validation.warnings, ...plan.validation.violations].length ? (
        <ul className="validation-findings">
          {[...plan.validation.warnings, ...plan.validation.violations].map((item) => <li key={item}>{item}</li>)}
        </ul>
      ) : null}
      <div className="plan-sections">
        <section><span>{t('plan.nutrition')}</span><h2>{t('plan.dietPlan')}</h2><pre>{JSON.stringify(plan.diet_plan, null, 2)}</pre></section>
        <section><span>{t('plan.training')}</span><h2>{t('plan.workoutPlan')}</h2><pre>{JSON.stringify(plan.workout_plan, null, 2)}</pre></section>
      </div>
    </section>
  )
}
