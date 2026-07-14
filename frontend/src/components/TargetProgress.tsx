import type { TargetProgress as TargetProgressType } from '../types'
import { useTranslation } from 'react-i18next'

export function TargetProgress({ target }: { target: TargetProgressType }) {
  const { t } = useTranslation()
  const ratio = target.target > 0 ? target.current / target.target : 0
  const remaining = Math.max(0, target.remaining)

  return (
    <div className={`target-progress ${target.status}`}>
      <div className="target-progress-heading">
        <span>{target.label === 'Calories' ? t('components.targetCalories') : target.label === 'Protein' ? t('components.targetProtein') : target.label}</span>
        <strong>{Math.round(target.current)} / {Math.round(target.target)} {target.unit}</strong>
      </div>
      <div className="target-progress-track" aria-hidden="true">
        <span style={{ width: `${Math.min(100, ratio * 100)}%` }} />
      </div>
      <small>{target.status === 'over'
        ? t('components.over', { value: Math.abs(Math.round(target.remaining)), unit: target.unit })
        : t('components.remaining', { value: Math.round(remaining), unit: target.unit })}</small>
    </div>
  )
}
