import { ChevronDown, ChevronUp, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import {
  resizeSetRows,
  type SelectedStrengthExercise,
} from '../../domain/workoutEntry'

interface StrengthExerciseEditorProps {
  item: SelectedStrengthExercise
  estimatedCalories?: number | null
  onChange: (next: SelectedStrengthExercise) => void
  onRemove: () => void
}

export function StrengthExerciseEditor({
  item,
  estimatedCalories,
  onChange,
  onRemove,
}: StrengthExerciseEditorProps) {
  const { t } = useTranslation()

  function setCount(value: string) {
    onChange({
      ...item,
      setCount: value,
      setRows: item.expanded
        ? resizeSetRows(item.setRows, value, item)
        : [],
    })
  }

  function toggleExpanded() {
    onChange({
      ...item,
      expanded: !item.expanded,
      setRows: resizeSetRows(item.setRows, item.setCount, item),
    })
  }

  return (
    <article className="workout-exercise-card">
      <header>
        <div>
          <strong>{item.exercise.name}</strong>
          <span>{item.exercise.primary_muscle}</span>
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

      <div className="compact-set-fields">
        <label>
          <span>{t('workoutEntry.sets')}</span>
          <input
            aria-label={t('workoutEntry.setsFor', { exercise: item.exercise.name })}
            type="number"
            min="1"
            step="1"
            value={item.setCount}
            onChange={(event) => setCount(event.target.value)}
          />
        </label>
        <label>
          <span>{t('workoutEntry.reps')}</span>
          <input
            aria-label={t('workoutEntry.repsFor', { exercise: item.exercise.name })}
            type="number"
            min="1"
            step="1"
            value={item.reps}
            disabled={item.expanded}
            onChange={(event) => onChange({
              ...item,
              reps: event.target.value,
              setRows: [],
            })}
          />
        </label>
        <label>
          <span>{t('workoutEntry.loadKg')}</span>
          <input
            aria-label={t('workoutEntry.loadFor', { exercise: item.exercise.name })}
            type="number"
            min="0"
            step="0.5"
            value={item.load}
            disabled={item.bodyweight || item.expanded}
            onChange={(event) => onChange({
              ...item,
              load: event.target.value,
              setRows: [],
            })}
          />
        </label>
        <label className="bodyweight-toggle">
          <input
            type="checkbox"
            checked={item.bodyweight}
            disabled={item.expanded}
            onChange={(event) => onChange({
              ...item,
              bodyweight: event.target.checked,
              load: event.target.checked ? '' : item.load,
              setRows: [],
            })}
          />
          <span>{t('workoutEntry.bodyweight')}</span>
        </label>
      </div>

      <button
        type="button"
        className="set-expander"
        disabled={!item.setCount}
        onClick={toggleExpanded}
      >
        {item.expanded ? <ChevronUp size={17} /> : <ChevronDown size={17} />}
        {item.expanded ? t('workoutEntry.useCompactSets') : t('workoutEntry.editEachSet')}
      </button>

      {item.expanded ? (
        <div className="expanded-sets">
          {item.setRows.map((set, index) => (
            <div className="expanded-set-row" key={`${item.key}:set:${index + 1}`}>
              <strong>{t('workoutEntry.setNumber', { number: index + 1 })}</strong>
              <label>
                <span>{t('workoutEntry.reps')}</span>
                <input
                  aria-label={t('workoutEntry.setRepsFor', {
                    number: index + 1,
                    exercise: item.exercise.name,
                  })}
                  type="number"
                  min="1"
                  step="1"
                  value={set.reps}
                  onChange={(event) => onChange({
                    ...item,
                    setRows: item.setRows.map((row, rowIndex) => (
                      rowIndex === index ? { ...row, reps: event.target.value } : row
                    )),
                  })}
                />
              </label>
              <label>
                <span>{t('workoutEntry.loadKg')}</span>
                <input
                  aria-label={t('workoutEntry.setLoadFor', {
                    number: index + 1,
                    exercise: item.exercise.name,
                  })}
                  type="number"
                  min="0"
                  step="0.5"
                  value={set.load}
                  disabled={set.bodyweight}
                  onChange={(event) => onChange({
                    ...item,
                    setRows: item.setRows.map((row, rowIndex) => (
                      rowIndex === index ? { ...row, load: event.target.value } : row
                    )),
                  })}
                />
              </label>
              <label className="bodyweight-toggle">
                <input
                  aria-label={t('workoutEntry.setBodyweightFor', {
                    number: index + 1,
                    exercise: item.exercise.name,
                  })}
                  type="checkbox"
                  checked={set.bodyweight}
                  onChange={(event) => onChange({
                    ...item,
                    setRows: item.setRows.map((row, rowIndex) => (
                      rowIndex === index
                        ? {
                          ...row,
                          bodyweight: event.target.checked,
                          load: event.target.checked ? '' : row.load,
                        }
                        : row
                    )),
                  })}
                />
                <span>{t('workoutEntry.bodyweight')}</span>
              </label>
            </div>
          ))}
        </div>
      ) : null}

      {estimatedCalories != null ? (
        <p className="estimate-note">
          {t('workoutEntry.strengthEstimate', {
            calories: Math.round(estimatedCalories),
          })}
        </p>
      ) : null}
    </article>
  )
}
