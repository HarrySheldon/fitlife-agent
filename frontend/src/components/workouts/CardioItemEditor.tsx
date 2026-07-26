import { Activity, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import {
  cardioNeedsEnergySource,
  type SelectedCardioExercise,
} from '../../domain/workoutEntry'
import type { CardioItemSnapshot } from '../../types/workouts'

interface CardioItemEditorProps {
  item: SelectedCardioExercise
  estimate?: CardioItemSnapshot
  onChange: (next: SelectedCardioExercise) => void
  onRemove: () => void
}

export function CardioItemEditor({
  item,
  estimate,
  onChange,
  onRemove,
}: CardioItemEditorProps) {
  const { t } = useTranslation()
  return (
    <article className="workout-exercise-card cardio">
      <header>
        <div className="exercise-title-with-icon">
          <Activity size={18} />
          <div>
            <strong>{item.exercise.name}</strong>
            <span>
              {item.exercise.met
                ? t('workoutEntry.metValue', { met: item.exercise.met })
                : item.exercise.primary_muscle}
            </span>
          </div>
        </div>
        <button
          type="button"
          className="icon-button destructive"
          aria-label={t('workoutEntry.removeExercise', { exercise: item.exercise.name })}
          title={t('workoutEntry.remove')}
          onClick={onRemove}
        >
          <Trash2 size={17} />
        </button>
      </header>

      <div className="cardio-fields">
        <label>
          <span>{t('workoutEntry.durationMinutes')}</span>
          <input
            aria-label={t('workoutEntry.durationFor', { exercise: item.exercise.name })}
            type="number"
            min="0.1"
            step="0.1"
            value={item.duration}
            onChange={(event) => onChange({ ...item, duration: event.target.value })}
          />
        </label>
        <label>
          <span>{t('workoutEntry.deviceCalories')}</span>
          <input
            aria-label={t('workoutEntry.deviceCaloriesFor', { exercise: item.exercise.name })}
            type="number"
            min="0"
            step="0.1"
            value={item.deviceCalories}
            onChange={(event) => onChange({ ...item, deviceCalories: event.target.value })}
          />
          <small>{t('workoutEntry.deviceCaloriesHint')}</small>
        </label>
      </div>

      {cardioNeedsEnergySource(item) ? (
        <p className="field-hint warning">{t('workoutEntry.cardioEnergyRequired')}</p>
      ) : null}

      {estimate ? (
        <p className={`estimate-note ${estimate.is_estimate ? '' : 'measured'}`}>
          {estimate.is_estimate
            ? t('workoutEntry.metEstimate', {
              calories: Math.round(estimate.estimated_calories),
            })
            : t('workoutEntry.deviceCaloriesResult', {
              calories: Math.round(estimate.estimated_calories),
            })}
        </p>
      ) : null}
    </article>
  )
}
