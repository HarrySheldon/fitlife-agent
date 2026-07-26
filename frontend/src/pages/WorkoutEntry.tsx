import { ArrowLeft } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { ExerciseCatalogPane } from '../components/workouts/ExerciseCatalogPane'
import { WorkoutDraftPane } from '../components/workouts/WorkoutDraftPane'
import {
  isWorkoutComplete,
  newCardioExercise,
  newStrengthExercise,
  workoutDraftInput,
  type SelectedCardioExercise,
  type SelectedStrengthExercise,
  type WorkoutSessionForm,
} from '../domain/workoutEntry'
import { useAuth } from '../hooks/useAuth'
import {
  useWorkoutDraft,
  type PendingWorkoutConfirmation,
} from '../hooks/useWorkoutDraft'
import { workoutApi } from '../services/workoutApi'
import type {
  ExerciseCatalogItem,
  WorkoutDraft,
  WorkoutDraftCreate,
} from '../types/workouts'

export function WorkoutEntry() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [params] = useSearchParams()
  const initialDate = validDate(params.get('date')) ?? browserDate()
  const ownerId = user?.user_id ?? 'anonymous'
  const initialRecoveryKey = workoutRecoveryKey(ownerId, initialDate)
  const recovered = useMemo(
    () => readRecovery(initialRecoveryKey),
    [initialRecoveryKey],
  )
  const [session, setSession] = useState<WorkoutSessionForm>(() => recovered?.session ?? ({
    logDate: initialDate,
    title: t('workoutEntry.defaultTitle'),
    startedAt: '',
    duration: '',
    intensity: '',
  }))
  const [strength, setStrength] = useState<SelectedStrengthExercise[]>(
    () => recovered?.strength ?? [],
  )
  const [cardio, setCardio] = useState<SelectedCardioExercise[]>(
    () => recovered?.cardio ?? [],
  )
  const [recoveryDraftId, setRecoveryDraftId] = useState<string | null>(
    recovered?.draftId ?? null,
  )
  const [recoveryReady, setRecoveryReady] = useState(false)
  const autosaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const confirmed = useRef(false)
  const recoveryStarted = useRef(false)
  const previousRecoveryKey = useRef(initialRecoveryKey)
  const initialDraft = useMemo<WorkoutDraftCreate>(() => (
    emptyWorkoutDraft(session)
  ), [])
  const draft = useWorkoutDraft(initialDraft)
  const canSubmit = isWorkoutComplete(session, strength, cardio)
  const recoveryKey = workoutRecoveryKey(ownerId, session.logDate)
  const dirty = hasDraftActivity(
    session,
    strength,
    cardio,
    initialDate,
    t('workoutEntry.defaultTitle'),
  )

  useEffect(() => {
    if (recoveryStarted.current) return
    recoveryStarted.current = true
    if (recovered?.pendingConfirmation) {
      draft.restorePendingConfirmation(recovered.pendingConfirmation)
      setRecoveryReady(true)
      return
    }
    void recoverServerDraft(
      recoveryDraftId,
      initialDate,
      draft.restore,
    ).then((serverDraft) => {
      if (serverDraft) {
        setRecoveryDraftId(serverDraft.id)
        if (!recovered) {
          const serverRecovery = recoveryFromDraft(serverDraft)
          setSession(serverRecovery.session)
          setStrength(serverRecovery.strength)
          setCardio(serverRecovery.cardio)
        }
      } else {
        setRecoveryDraftId(null)
      }
    }).finally(() => setRecoveryReady(true))
  }, [draft.restore, draft.restorePendingConfirmation, initialDate, recovered, recoveryDraftId])

  useEffect(() => {
    if (!recoveryReady || !draft.pendingConfirmation || !canSubmit) return
    void draft.saveAndConfirm(currentInput())
      .then(() => completeConfirmation())
      .catch(() => undefined)
  }, [canSubmit, draft.pendingConfirmation, recoveryReady])

  useEffect(() => {
    if (confirmed.current) return
    if (previousRecoveryKey.current !== recoveryKey) {
      removeRecovery(previousRecoveryKey.current)
      previousRecoveryKey.current = recoveryKey
    }
    writeRecovery(recoveryKey, {
      session,
      strength,
      cardio,
      draftId: draft.draft?.id ?? recoveryDraftId,
      pendingConfirmation: draft.pendingConfirmation,
    })
  }, [cardio, draft.draft?.id, draft.pendingConfirmation, recoveryDraftId, recoveryKey, session, strength])

  useEffect(() => {
    if (!recoveryReady || !dirty || draft.pendingConfirmation) return
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current)
    autosaveTimer.current = setTimeout(() => {
      const input = canSubmit
        ? withRecoveryState(
          workoutDraftInput(session, strength, cardio),
          recoverySnapshot(null),
        )
        : recoverableServerDraft(
          session,
          strength,
          cardio,
          initialDate,
          t('workoutEntry.defaultTitle'),
        )
      void draft.save(input)
        .then((saved) => setRecoveryDraftId(saved.id))
        .catch(() => undefined)
    }, 1200)
    return () => {
      if (autosaveTimer.current) clearTimeout(autosaveTimer.current)
    }
  }, [canSubmit, cardio, dirty, draft.pendingConfirmation, draft.save, initialDate, recoveryReady, session, strength, t])

  function addExercise(exercise: ExerciseCatalogItem) {
    if (exercise.exercise_type === 'strength') {
      setStrength((current) => current.some((item) => item.exercise.id === exercise.id)
        ? current
        : [...current, newStrengthExercise(exercise)])
      return
    }
    setCardio((current) => current.some((item) => item.exercise.id === exercise.id)
      ? current
      : [...current, newCardioExercise(exercise)])
  }

  function currentInput() {
    return withRecoveryState(
      workoutDraftInput(session, strength, cardio),
      recoverySnapshot(null),
    )
  }

  function recoverySnapshot(
    pendingConfirmation: PendingWorkoutConfirmation | null,
  ): WorkoutRecovery {
    return {
      session,
      strength,
      cardio,
      draftId: draft.draft?.id ?? recoveryDraftId,
      pendingConfirmation,
    }
  }

  async function saveDraft() {
    if (!canSubmit) return
    try {
      clearAutosave()
      const saved = await draft.save(currentInput())
      setRecoveryDraftId(saved.id)
    } catch {
      // The hook owns recoverable errors and retry state.
    }
  }

  async function confirmWorkout() {
    if (!canSubmit) return
    try {
      clearAutosave()
      await draft.saveAndConfirm(currentInput())
      completeConfirmation()
    } catch {
      // Keep the editor intact until the user retries or resolves a conflict.
    }
  }

  function completeConfirmation() {
    confirmed.current = true
    removeRecovery(recoveryKey)
    navigate('/', { replace: true })
  }

  function clearAutosave() {
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current)
    autosaveTimer.current = null
  }

  async function retryConflict() {
    try {
      await draft.resolveConflict('overwrite')
    } catch {
      // Leave the current form available for another explicit retry.
    }
  }

  return (
    <div className="page-stack workout-entry-page">
      <header className="workout-entry-header">
        <button
          type="button"
          className="icon-button"
          aria-label={t('workoutEntry.back')}
          title={t('workoutEntry.back')}
          onClick={() => navigate('/')}
        >
          <ArrowLeft size={19} />
        </button>
        <div>
          <span>{t('workoutEntry.eyebrow')}</span>
          <h1>{t('workoutEntry.title')}</h1>
        </div>
      </header>

      <div className="workout-entry-workspace">
        <ExerciseCatalogPane
          selectedCatalogIds={[
            ...strength.map((item) => item.exercise.id),
            ...cardio.map((item) => item.exercise.id),
          ]}
          onAddExercise={addExercise}
        />
        <WorkoutDraftPane
          session={session}
          strength={strength}
          cardio={cardio}
          savedDraft={draft.draft}
          status={draft.status}
          error={draft.error}
          canSubmit={canSubmit}
          canRetryConflict={draft.draft !== null}
          onSessionChange={setSession}
          onStrengthChange={(key, next) => setStrength((current) => current.map((item) => (
            item.key === key ? next : item
          )))}
          onCardioChange={(key, next) => setCardio((current) => current.map((item) => (
            item.key === key ? next : item
          )))}
          onRemoveStrength={(key) => setStrength((current) => (
            current.filter((item) => item.key !== key)
          ))}
          onRemoveCardio={(key) => setCardio((current) => (
            current.filter((item) => item.key !== key)
          ))}
          onSave={() => void saveDraft()}
          onConfirm={() => void confirmWorkout()}
          onRetryConflict={() => void retryConflict()}
        />
      </div>
    </div>
  )
}

function validDate(value: string | null): string | null {
  return value && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null
}

function browserDate(): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]))
  return `${values.year}-${values.month}-${values.day}`
}

interface WorkoutRecovery {
  session: WorkoutSessionForm
  strength: SelectedStrengthExercise[]
  cardio: SelectedCardioExercise[]
  draftId: string | null
  pendingConfirmation: PendingWorkoutConfirmation | null
}

function emptyWorkoutDraft(session: WorkoutSessionForm): WorkoutDraftCreate {
  return {
    log_date: session.logDate,
    title: session.title,
    started_at: null,
    duration_min: null,
    intensity: null,
    entry_method: 'form',
    strength_exercises: [],
    cardio_items: [],
  }
}

async function recoverServerDraft(
  draftId: string | null,
  logDate: string,
  restore: (draftId: string) => Promise<WorkoutDraft>,
): Promise<WorkoutDraft | null> {
  if (draftId) {
    try {
      return await restore(draftId)
    } catch {
      // Fall through to date discovery when a local pointer is stale.
    }
  }
  try {
    const latest = await workoutApi.findLatestDraft(logDate)
    if (!latest) return null
    await restore(latest.id)
    return latest
  } catch {
    return null
  }
}

function recoveryFromDraft(draft: WorkoutDraft): WorkoutRecovery {
  const editorRecovery = parseRecovery(draft.payload.recovery_state)
  if (editorRecovery) {
    return {
      ...editorRecovery,
      draftId: draft.id,
      pendingConfirmation: null,
    }
  }
  const startedAt = draft.payload.started_at?.match(/T(\d{2}:\d{2})/)?.[1] ?? ''
  return {
    session: {
      logDate: draft.payload.log_date,
      title: draft.payload.title,
      startedAt,
      duration: draft.payload.duration_min != null
        ? String(draft.payload.duration_min)
        : '',
      intensity: draft.payload.intensity ?? '',
    },
    strength: draft.payload.strength_exercises.map((exercise) => {
      const first = exercise.sets[0]
      const compact = exercise.sets.every((set) => (
        set.reps === first?.reps
        && set.load_kg === first?.load_kg
        && set.bodyweight === first?.bodyweight
      ))
      const item = newStrengthExercise(catalogExercise({
        id: exercise.catalog_exercise_id ?? `recovered:${exercise.exercise_name}`,
        name: exercise.exercise_name,
        exerciseType: 'strength',
        primaryMuscle: exercise.primary_muscle,
        secondaryMuscles: exercise.secondary_muscles,
        met: null,
      }))
      return {
        ...item,
        setCount: String(exercise.sets.length),
        reps: compact && first ? String(first.reps) : '',
        load: compact && first?.load_kg != null ? String(first.load_kg) : '',
        bodyweight: compact ? Boolean(first?.bodyweight) : false,
        expanded: !compact,
        setRows: exercise.sets.map((set) => ({
          reps: String(set.reps),
          load: set.load_kg != null ? String(set.load_kg) : '',
          bodyweight: set.bodyweight,
        })),
      }
    }),
    cardio: draft.payload.cardio_items.map((item) => ({
      ...newCardioExercise(catalogExercise({
        id: item.catalog_exercise_id ?? `recovered:${item.activity_name}`,
        name: item.activity_name,
        exerciseType: 'cardio',
        primaryMuscle: item.primary_muscle,
        secondaryMuscles: item.secondary_muscles,
        met: item.met,
      })),
      duration: String(item.duration_min),
      deviceCalories: item.device_calories != null
        ? String(item.device_calories)
        : '',
    })),
    draftId: draft.id,
    pendingConfirmation: null,
  }
}

function catalogExercise({
  id,
  name,
  exerciseType,
  primaryMuscle,
  secondaryMuscles,
  met,
}: {
  id: string
  name: string
  exerciseType: ExerciseCatalogItem['exercise_type']
  primaryMuscle: string
  secondaryMuscles: string[]
  met: number | null
}): ExerciseCatalogItem {
  return {
    id,
    owner_user_id: null,
    source: 'snapshot',
    source_name: 'confirmed-draft-snapshot',
    source_record_id: id,
    dataset_version: null,
    name,
    exercise_type: exerciseType,
    primary_muscle: primaryMuscle,
    secondary_muscles: secondaryMuscles,
    met,
    license: null,
    attribution: null,
    provenance: {},
    content_hash: null,
    active: true,
    aliases: [],
    is_favorite: false,
    use_count: 0,
    last_used_at: null,
    rank_group: 0,
  }
}

function hasDraftActivity(
  session: WorkoutSessionForm,
  strength: SelectedStrengthExercise[],
  cardio: SelectedCardioExercise[],
  initialDate: string,
  defaultTitle: string,
): boolean {
  return strength.length > 0
    || cardio.length > 0
    || session.logDate !== initialDate
    || session.title !== defaultTitle
    || Boolean(session.startedAt || session.duration || session.intensity)
}

function recoverableServerDraft(
  session: WorkoutSessionForm,
  strength: SelectedStrengthExercise[],
  cardio: SelectedCardioExercise[],
  fallbackDate: string,
  defaultTitle: string,
): WorkoutDraftCreate {
  const logDate = validDate(session.logDate) ?? fallbackDate
  const duration = Number(session.duration)
  const validDuration = session.duration.trim()
    && Number.isFinite(duration)
    && duration > 0
  const startedAt = /^\d{2}:\d{2}$/.test(session.startedAt)
    ? `${logDate}T${session.startedAt}:00`
    : null
  return withRecoveryState({
    log_date: logDate,
    title: session.title.trim() || defaultTitle,
    started_at: startedAt,
    duration_min: validDuration ? duration : null,
    intensity: session.intensity || null,
    entry_method: 'form',
    strength_exercises: [],
    cardio_items: [],
  }, {
    session: { ...session, logDate },
    strength,
    cardio,
    draftId: null,
    pendingConfirmation: null,
  })
}

function withRecoveryState(
  input: WorkoutDraftCreate,
  recovery: WorkoutRecovery,
): WorkoutDraftCreate {
  return {
    ...input,
    recovery_state: JSON.parse(JSON.stringify(recovery)) as Record<string, unknown>,
  }
}

function workoutRecoveryKey(userId: string, date: string): string {
  return `fitlife:workout-draft:${userId}:${date}`
}

function readRecovery(key: string): WorkoutRecovery | null {
  try {
    const value = globalThis.localStorage.getItem(key)
    if (!value) return null
    return parseRecovery(JSON.parse(value))
  } catch {
    return null
  }
}

function parseRecovery(value: unknown): WorkoutRecovery | null {
  if (!value || typeof value !== 'object') return null
  const parsed = value as Partial<WorkoutRecovery>
  if (
    !parsed.session
    || typeof parsed.session.logDate !== 'string'
    || typeof parsed.session.title !== 'string'
    || !Array.isArray(parsed.strength)
    || !Array.isArray(parsed.cardio)
  ) return null
  return {
    session: parsed.session,
    strength: parsed.strength,
    cardio: parsed.cardio,
    draftId: typeof parsed.draftId === 'string' ? parsed.draftId : null,
    pendingConfirmation: validPendingConfirmation(parsed.pendingConfirmation)
      ? parsed.pendingConfirmation
      : null,
  }
}

function validPendingConfirmation(
  value: unknown,
): value is PendingWorkoutConfirmation {
  if (!value || typeof value !== 'object') return false
  const pending = value as Record<string, unknown>
  return typeof pending.draftId === 'string'
    && typeof pending.version === 'number'
    && typeof pending.idempotencyKey === 'string'
    && typeof pending.fingerprint === 'string'
}

function writeRecovery(key: string, value: WorkoutRecovery): void {
  try {
    globalThis.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Storage can be unavailable in privacy-restricted browser contexts.
  }
}

function removeRecovery(key: string): void {
  try {
    globalThis.localStorage.removeItem(key)
  } catch {
    // Confirmation remains authoritative even if local cleanup is unavailable.
  }
}
