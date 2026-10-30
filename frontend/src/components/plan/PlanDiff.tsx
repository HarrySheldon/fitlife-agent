import { useTranslation } from 'react-i18next'
import type { PlanTaskCandidate } from '../../types'

export function PlanDiff({ candidate }: { candidate: PlanTaskCandidate }) {
  const { t } = useTranslation()
  return <section aria-label={t('plan.planTask.diffTitle')}>
    <h3>{t('plan.planTask.diffTitle')}</h3>
    {(candidate.diff ?? []).map(item => <article key={item.path} className="content-panel">
      <strong>{t(`plan.planTask.domain.${item.domain}`)} · {item.path}</strong>
      <p>{t('plan.planTask.before')}</p><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(item.old_value, null, 2)}</pre>
      <p>{t('plan.planTask.after')}</p><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(item.new_value, null, 2)}</pre>
      <small>{t('plan.planTask.diffSource')}</small>
    </article>)}
  </section>
}
