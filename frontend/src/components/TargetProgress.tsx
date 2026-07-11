import type { TargetProgress as TargetProgressType } from '../types'

export function TargetProgress({ target }: { target: TargetProgressType }) {
  const ratio = target.target > 0 ? target.current / target.target : 0
  const remaining = Math.max(0, target.remaining)

  return (
    <div className={`target-progress ${target.status}`}>
      <div className="target-progress-heading">
        <span>{target.label}</span>
        <strong>{Math.round(target.current)} / {Math.round(target.target)} {target.unit}</strong>
      </div>
      <div className="target-progress-track" aria-hidden="true">
        <span style={{ width: `${Math.min(100, ratio * 100)}%` }} />
      </div>
      <small>{target.status === 'over' ? `${Math.abs(Math.round(target.remaining))} ${target.unit} over` : `${Math.round(remaining)} ${target.unit} remaining`}</small>
    </div>
  )
}
