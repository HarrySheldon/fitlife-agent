import { useTranslation } from 'react-i18next'
import type { PlanTaskCandidate } from '../../types'

const FIELD_KEYS = new Set(['summary','days','day','type','focus','intensity','exercises','name','sets','reps',
  'rest_seconds','duration_min','weekly_training_days','rest_days','daily_calorie_target','daily_protein_target','meals',
  'weight','weight_kg','calories','protein','carbs','fat','amount','unit','food','meal_type'])
const UNITS: Record<string,string> = { sets:'sets', reps:'reps', rest_seconds:'seconds', duration_min:'minutes',
  weekly_training_days:'days', daily_calorie_target:'kcal', daily_protein_target:'grams',
  weight_kg:'kg',calories:'kcal',protein:'grams',carbs:'grams',fat:'grams' }

export function PlanDiff({ candidate }: { candidate: PlanTaskCandidate }) {
  const { t } = useTranslation()
  const label = (key: string) => FIELD_KEYS.has(key) ? t(`plan.diff.fields.${key}`) : t('plan.diff.otherField',{name:key})
  function value(node: unknown, key: string): React.ReactNode {
    if (node === null || node === undefined) return t('plan.diff.unset')
    if (Array.isArray(node)) return node.length ? <ul>{node.map((item,index)=><li key={index}>{value(item,key)}</li>)}</ul> : t('plan.diff.empty')
    if (typeof node === 'object') return <dl>{Object.entries(node).map(([field,item])=><div key={field}><dt>{label(field)}</dt><dd>{value(item,field)}</dd></div>)}</dl>
    if (typeof node === 'boolean') return t(node ? 'plan.diff.yes':'plan.diff.no')
    return <>{String(node)}{typeof node==='number' && UNITS[key] ? ` ${t(`plan.diff.units.${UNITS[key]}`)}` : ''}</>
  }
  return <section aria-label={t('plan.planTask.diffTitle')}>
    <h3>{t('plan.planTask.diffTitle')}</h3>
    <p>{t('plan.diff.summary',{count:candidate.diff?.length ?? 0})}</p>
    {(['training','diet'] as const).map(domain=><p key={domain}>{t(`plan.planTask.domain.${domain}`)}：{
      candidate.diff?.some(item=>item.domain===domain) ? t('plan.diff.changed') : t('plan.diff.unchanged')}</p>)}
    {(candidate.diff ?? []).map(item => {
      const parts=item.path.split('.'), field=parts[parts.length-1]
      const title=item.context?.length ? [...item.context,label(/^\d+$/.test(field) ? parts[parts.length-2] : field)]
        : parts.slice(1).map(part=>/^\d+$/.test(part) ? t('plan.diff.item',{number:Number(part)+1}) : label(part))
      return <article key={item.path} className="content-panel plan-diff-item">
        <h4>{t(`plan.planTask.domain.${item.domain}`)} · {title.join(' / ')}</h4>
        <p>{t(`plan.diff.kind.${item.change_kind ?? 'changed'}`)}</p>
        <div className="plan-diff-values">
          <section><h5>{t('plan.planTask.before')}</h5>{item.change_kind==='added' ? t('plan.diff.absent'):value(item.old_value,field)}</section>
          <section><h5>{t('plan.planTask.after')}</h5>{item.change_kind==='removed' ? t('plan.diff.absent'):value(item.new_value,field)}</section>
        </div>
        <small>{t('plan.planTask.diffSource')}</small>
        <details><summary>{t('plan.diff.technical')}</summary><code>{item.path}</code>
          <pre>{JSON.stringify({before:item.old_value,after:item.new_value},null,2)}</pre></details>
      </article>
    })}
  </section>
}
