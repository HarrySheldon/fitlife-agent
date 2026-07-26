import { useCallback, useRef, useState } from 'react'

import { workoutApi } from '../services/workoutApi'
import type {
  ConfirmedWorkout,
  WorkoutDraft,
  WorkoutDraftCreate,
  WorkoutDraftPayload,
} from '../types/workouts'

export type WorkoutDraftStatus =
  | 'idle'
  | 'saving'
  | 'conflict'
  | 'confirming'
  | 'confirmed'
  | 'error'

export interface PendingWorkoutConfirmation {
  draftId: string
  version: number
  idempotencyKey: string
  fingerprint: string
}

export function useWorkoutDraft(initialInput: WorkoutDraftCreate) {
  const [input, setInputState] = useState(initialInput)
  const inputRef = useRef(initialInput)
  const [draft, setDraft] = useState<WorkoutDraft | null>(null)
  const draftRef = useRef<WorkoutDraft | null>(null)
  const [confirmedWorkout, setConfirmedWorkout] = useState<ConfirmedWorkout | null>(null)
  const [status, setStatus] = useState<WorkoutDraftStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const confirmationKey = useRef<string | null>(null)
  const confirmationFingerprint = useRef<string | null>(null)
  const pendingRef = useRef<PendingWorkoutConfirmation | null>(null)
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingWorkoutConfirmation | null>(null)
  const commandActive = useRef(false)

  const setInput = useCallback((next: WorkoutDraftCreate) => {
    inputRef.current = next
    setInputState(next)
    setStatus((current) => current === 'conflict' ? 'conflict' : 'idle')
    setError(null)
  }, [])

  const storeDraft = useCallback((next: WorkoutDraft) => {
    draftRef.current = next
    setDraft(next)
    confirmationKey.current = null
    confirmationFingerprint.current = null
    pendingRef.current = null
    setPendingConfirmation(null)
  }, [])

  const runCommand = useCallback(async <T,>(
    nextStatus: Extract<WorkoutDraftStatus, 'saving' | 'confirming'>,
    command: () => Promise<T>,
  ) => {
    if (commandActive.current) throw new Error('WORKOUT_DRAFT_OPERATION_IN_PROGRESS')
    commandActive.current = true
    setStatus(nextStatus)
    setError(null)
    try {
      return await command()
    } catch (cause) {
      const conflict = (
        typeof cause === 'object'
        && cause !== null
        && 'status' in cause
        && cause.status === 409
      )
      setStatus(conflict ? 'conflict' : 'error')
      setError((cause as Error).message)
      throw cause
    } finally {
      commandActive.current = false
    }
  }, [])

  const save = useCallback(async (nextInput?: WorkoutDraftCreate) => {
    const payload = nextInput ?? inputRef.current
    if (nextInput) setInput(nextInput)
    return runCommand('saving', async () => {
      const current = draftRef.current
      const saved = current
        ? await workoutApi.updateDraft(current.id, current.version, payload)
        : await workoutApi.createDraft(payload)
      storeDraft(saved)
      setStatus('idle')
      return saved
    })
  }, [runCommand, setInput, storeDraft])

  const restore = useCallback(async (draftId: string) => (
    runCommand('saving', async () => {
      const restored = await workoutApi.getDraft(draftId)
      storeDraft(restored)
      setStatus('idle')
      return restored
    })
  ), [runCommand, storeDraft])

  const resolveConflict = useCallback(async (
    resolution: 'reload' | 'overwrite',
  ) => {
    const current = draftRef.current
    if (!current) throw new Error('WORKOUT_DRAFT_REQUIRED')
    return runCommand('saving', async () => {
      const latest = await workoutApi.getDraft(current.id)
      if (resolution === 'reload') {
        storeDraft(latest)
        const reloadedInput = draftPayloadToInput(latest.payload)
        inputRef.current = reloadedInput
        setInputState(reloadedInput)
        setStatus('idle')
        return latest
      }
      const saved = await workoutApi.updateDraft(
        latest.id,
        latest.version,
        inputRef.current,
      )
      storeDraft(saved)
      setStatus('idle')
      return saved
    })
  }, [runCommand, storeDraft])

  const confirm = useCallback(async () => {
    const current = draftRef.current
    if (!current) throw new Error('WORKOUT_DRAFT_REQUIRED')
    return runCommand('confirming', async () => {
      confirmationKey.current ??= globalThis.crypto.randomUUID()
      const confirmed = await workoutApi.confirmDraft(
        current.id,
        current.version,
        confirmationKey.current,
      )
      setConfirmedWorkout(confirmed)
      setStatus('confirmed')
      return confirmed
    })
  }, [runCommand])

  const saveAndConfirm = useCallback(async (nextInput: WorkoutDraftCreate) => {
    const fingerprint = confirmationFingerprintFor(nextInput)
    let pending = pendingRef.current
    if (!pending || pending.fingerprint !== fingerprint) {
      const saved = await save(nextInput)
      pending = {
        draftId: saved.id,
        version: saved.version,
        idempotencyKey: globalThis.crypto.randomUUID(),
        fingerprint,
      }
      pendingRef.current = pending
      setPendingConfirmation(pending)
    }
    return runCommand('confirming', async () => {
      const confirmed = await workoutApi.confirmDraft(
        pending.draftId,
        pending.version,
        pending.idempotencyKey,
      )
      setConfirmedWorkout(confirmed)
      pendingRef.current = null
      setPendingConfirmation(null)
      setStatus('confirmed')
      return confirmed
    })
  }, [runCommand, save])

  const restorePendingConfirmation = useCallback((
    pending: PendingWorkoutConfirmation,
  ) => {
    pendingRef.current = pending
    setPendingConfirmation(pending)
  }, [])

  const discard = useCallback(async () => {
    const current = draftRef.current
    if (current) await workoutApi.deleteDraft(current.id)
    draftRef.current = null
    setDraft(null)
    confirmationKey.current = null
    confirmationFingerprint.current = null
    pendingRef.current = null
    setPendingConfirmation(null)
    setStatus('idle')
    setError(null)
  }, [])

  return {
    input,
    draft,
    confirmedWorkout,
    pendingConfirmation,
    status,
    error,
    setInput,
    save,
    restore,
    resolveConflict,
    confirm,
    saveAndConfirm,
    restorePendingConfirmation,
    discard,
  }
}

function confirmationFingerprintFor(input: WorkoutDraftCreate): string {
  const { recovery_state: _recoveryState, ...confirmedFields } = input
  return JSON.stringify(confirmedFields)
}

function draftPayloadToInput(payload: WorkoutDraftPayload): WorkoutDraftCreate {
  return {
    log_date: payload.log_date,
    title: payload.title,
    started_at: payload.started_at,
    duration_min: payload.duration_min,
    intensity: payload.intensity,
    entry_method: 'form',
    strength_exercises: payload.strength_exercises.map((exercise) => ({
      ...(exercise.catalog_exercise_id
        ? { catalog_exercise_id: exercise.catalog_exercise_id }
        : { custom_exercise: requiredCustom(exercise.custom_exercise) }),
      sets: exercise.sets,
    })),
    cardio_items: payload.cardio_items.map((item) => ({
      ...(item.catalog_exercise_id
        ? { catalog_exercise_id: item.catalog_exercise_id }
        : { custom_exercise: requiredCustom(item.custom_exercise) }),
      duration_min: item.duration_min,
      device_calories: item.device_calories,
    })),
  }
}

function requiredCustom<T>(custom: T | null): T {
  if (!custom) throw new Error('WORKOUT_DRAFT_EXERCISE_SOURCE_REQUIRED')
  return custom
}
