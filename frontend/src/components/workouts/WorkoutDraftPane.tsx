import {
  AlertTriangle,
  Check,
  Dumbbell,
  HeartPulse,
  RefreshCw,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type {
  SelectedCardioExercise,
  SelectedStrengthExercise,
  WorkoutSessionForm,
} from '../../domain/workoutEntry'
import { workoutDraftInput } from '../../domain/workoutEntry'
import type { WorkoutDraftStatus } from '../../hooks/useWorkoutDraft'
import type { WorkoutDraft } from '../../types/workouts'
import { CardioItemEditor } from './CardioItemEditor'
import { StrengthExerciseEditor } from './StrengthExerciseEditor'

interface WorkoutDraftPaneProps {
  session: WorkoutSessionForm
  strength: SelectedStrengthExercise[]
  cardio: SelectedCardioExercise[]
  savedDraft: WorkoutDraft | null
  status: WorkoutDraftStatus
  error: string | null
  canSubmit: boolean
  canRetryConflict: boolean
  onSessionChange: (next: WorkoutSessionForm) => void
  onStrengthChange: (key: string, next: SelectedStrengthExercise) => void
  onCardioChange: (key: string, next: SelectedCardioExercise) => void
  onRemoveStrength: (key: string) => void
  onRemoveCardio: (key: string) => void
  onSave: () => void
  onConfirm: () => void
  onRetryConflict: () => void
}

export function WorkoutDraftPane({
  session,
  strength,
  cardio,
  savedDraft,
  status,
  error,
  canSubmit,
  canRetryConflict,
  onSessionChange,
  onStrengthChange,
  onCardioChange,
  onRemoveStrength,
  onRemoveCardio,
  onSave,
  onConfirm,
  onRetryConflict,
}: WorkoutDraftPaneProps) {
  const { t } = useTranslation()
  const busy = status === 'saving' || status === 'confirming'
  const estimatesCurrent = draftMatchesForm(
    savedDraft,
    session,
    strength,
    cardio,
  )
  const strengthCalories = estimatesCurrent
    ? strengthEstimateCalories(savedDraft)
    : null
  return (
    <section className="workout-draft-pane" aria-labelledby="workout-draft-title">
      <header className="workout-draft-heading">
        <div>
          <span>{t('workoutEntry.draftEyebrow')}</span>
          <h2 id="workout-draft-title">{t('workoutEntry.session')}</h2>
        </div>
        <strong>{strength.length + cardio.length}</strong>
      </header>

      <div className="workout-session-fields">
        <label className="wide">
          <span>{t('workoutEntry.sessionTitle')}</span>
          <input
            aria-label={t('workoutEntry.sessionTitle')}
            value={session.title}
            onChange={(event) => onSessionChange({ ...session, title: event.target.value })}
          />
        </label>
        <label>
          <span>{t('workoutEntry.date')}</span>
          <input
            aria-label={t('workoutEntry.date')}
            type="date"
            value={session.logDate}
            onChange={(event) => onSessionChange({ ...session, logDate: event.target.value })}
          />
        </label>
        <label>
          <span>{t('workoutEntry.startedAt')}</span>
          <input
            type="time"
            value={session.startedAt}
            onChange={(event) => onSessionChange({ ...session, startedAt: event.target.value })}
          />
        </label>
        <label>
          <span>{t('workoutEntry.sessionDuration')}</span>
          <input
            type="number"
            min="0.1"
            step="0.1"
            value={session.duration}
            onChange={(event) => onSessionChange({ ...session, duration: event.target.value })}
          />
        </label>
        <label>
          <span>{t('workoutEntry.intensity')}</span>
          <select
            value={session.intensity}
            onChange={(event) => onSessionChange({
              ...session,
              intensity: event.target.value as WorkoutSessionForm['intensity'],
            })}
          >
            <option value="">{t('workoutEntry.selectIntensity')}</option>
            <option value="low">{t('workoutEntry.intensities.low')}</option>
            <option value="medium">{t('workoutEntry.intensities.medium')}</option>
            <option value="high">{t('workoutEntry.intensities.high')}</option>
          </select>
        </label>
      </div>
      {session.duration && !session.intensity ? (
        <p className="field-hint warning">{t('workoutEntry.intensityRequired')}</p>
      ) : null}

      <WorkoutSection
        icon={<Dumbbell size={18} />}
        title={t('workoutEntry.strength')}
        count={strength.length}
        empty={t('workoutEntry.noStrength')}
      >
        {strength.map((item) => (
          <StrengthExerciseEditor
            key={item.key}
            item={item}
            onChange={(next) => onStrengthChange(item.key, next)}
            onRemove={() => onRemoveStrength(item.key)}
          />
        ))}
        {strength.length > 0 && strengthCalories != null ? (
          <p className="estimate-note session-estimate">
            {t('workoutEntry.strengthEstimate', {
              calories: Math.round(strengthCalories),
            })}
          </p>
        ) : null}
      </WorkoutSection>

      <WorkoutSection
        icon={<HeartPulse size={18} />}
        title={t('workoutEntry.cardio')}
        count={cardio.length}
        empty={t('workoutEntry.noCardio')}
      >
        {cardio.map((item) => (
          <CardioItemEditor
            key={item.key}
            item={item}
            estimate={estimatesCurrent
              ? savedDraft?.payload.cardio_items.find((saved) => (
                saved.catalog_exercise_id === item.exercise.id
              ))
              : undefined}
            onChange={(next) => onCardioChange(item.key, next)}
            onRemove={() => onRemoveCardio(item.key)}
          />
        ))}
      </WorkoutSection>

      {error ? (
        <div className={`draft-feedback ${status === 'conflict' ? 'conflict' : ''}`}>
          <AlertTriangle size={18} />
          <div>
            <strong>{status === 'conflict'
              ? t('workoutEntry.conflictTitle')
              : t('workoutEntry.saveFailed')}</strong>
            <span>{error}</span>
          </div>
        </div>
      ) : null}
      {status === 'conflict' && canRetryConflict ? (
        <button type="button" className="secondary-button" onClick={onRetryConflict}>
          <RefreshCw size={17} />
          {t('workoutEntry.retryChanges')}
        </button>
      ) : null}

      <footer className="workout-draft-actions">
        <button
          type="button"
          className="secondary-button"
          disabled={!canSubmit || busy}
          onClick={onSave}
        >
          {status === 'saving' ? t('common.saving') : t('workoutEntry.saveDraft')}
        </button>
        <button
          type="button"
          className="primary-button"
          disabled={!canSubmit || busy}
          onClick={onConfirm}
        >
          <Check size={18} />
          {status === 'confirming'
            ? t('workoutEntry.confirming')
            : t('workoutEntry.confirm')}
        </button>
      </footer>
    </section>
  )
}

function strengthEstimateCalories(draft: WorkoutDraft | null): number | null {
  const strength = draft?.payload.estimate.strength
  if (!strength || typeof strength !== 'object') return null
  const calories = (strength as Record<string, unknown>).calories
  return typeof calories === 'number' && Number.isFinite(calories)
    ? calories
    : null
}

function draftMatchesForm(
  draft: WorkoutDraft | null,
  session: WorkoutSessionForm,
  strength: SelectedStrengthExercise[],
  cardio: SelectedCardioExercise[],
): boolean {
  if (!draft) return false
  try {
    const current = workoutDraftInput(session, strength, cardio)
    const saved = {
      log_date: draft.payload.log_date,
      title: draft.payload.title,
      started_at: draft.payload.started_at,
      duration_min: draft.payload.duration_min,
      intensity: draft.payload.intensity,
      entry_method: 'form',
      strength_exercises: draft.payload.strength_exercises.map((exercise) => ({
        ...(exercise.catalog_exercise_id
          ? { catalog_exercise_id: exercise.catalog_exercise_id }
          : { custom_exercise: exercise.custom_exercise }),
        sets: exercise.sets,
      })),
      cardio_items: draft.payload.cardio_items.map((item) => ({
        ...(item.catalog_exercise_id
          ? { catalog_exercise_id: item.catalog_exercise_id }
          : { custom_exercise: item.custom_exercise }),
        duration_min: item.duration_min,
        device_calories: item.device_calories,
      })),
    }
    return JSON.stringify(current) === JSON.stringify(saved)
  } catch {
    return false
  }
}

function WorkoutSection({
  icon,
  title,
  count,
  empty,
  children,
}: {
  icon: React.ReactNode
  title: string
  count: number
  empty: string
  children: React.ReactNode
}) {
  return (
    <section className="workout-type-section">
      <header>
        <div>{icon}<h3>{title}</h3></div>
        <span>{count}</span>
      </header>
      {count ? children : <p className="workout-section-empty">{empty}</p>}
    </section>
  )
}
