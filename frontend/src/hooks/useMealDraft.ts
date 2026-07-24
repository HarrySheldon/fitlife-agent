import { useCallback, useRef, useState } from 'react'

import { mealApi } from '../services/mealApi'
import type {
  ConfirmedMeal,
  MealDraft,
  MealDraftCreate,
  MealDraftPayload,
} from '../types/meals'


export type MealDraftStatus =
  | 'idle'
  | 'saving'
  | 'conflict'
  | 'confirming'
  | 'confirmed'
  | 'error'

export function useMealDraft(initialInput: MealDraftCreate) {
  const [input, setInputState] = useState(initialInput)
  const inputRef = useRef(initialInput)
  const [draft, setDraft] = useState<MealDraft | null>(null)
  const draftRef = useRef<MealDraft | null>(null)
  const [confirmedMeal, setConfirmedMeal] = useState<ConfirmedMeal | null>(null)
  const [status, setStatus] = useState<MealDraftStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const confirmationKey = useRef<string | null>(null)
  const commandActive = useRef(false)

  const setInput = useCallback((next: MealDraftCreate) => {
    inputRef.current = next
    setInputState(next)
    setStatus((current) => current === 'conflict' ? 'conflict' : 'idle')
    setError(null)
  }, [])

  const storeDraft = useCallback((next: MealDraft) => {
    draftRef.current = next
    setDraft(next)
    confirmationKey.current = null
  }, [])

  const runCommand = useCallback(async <T,>(
    nextStatus: Extract<MealDraftStatus, 'saving' | 'confirming'>,
    command: () => Promise<T>,
  ) => {
    if (commandActive.current) throw new Error('MEAL_DRAFT_OPERATION_IN_PROGRESS')
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

  const save = useCallback(async (nextInput?: MealDraftCreate) => {
    const payload = nextInput ?? inputRef.current
    if (nextInput) setInput(nextInput)
    return runCommand('saving', async () => {
      const current = draftRef.current
      const saved = current
        ? await mealApi.updateDraft(current.id, current.version, payload)
        : await mealApi.createDraft(payload)
      storeDraft(saved)
      setStatus('idle')
      return saved
    })
  }, [runCommand, setInput, storeDraft])

  const resolveConflict = useCallback(async (
    resolution: 'reload' | 'overwrite',
  ) => {
    const current = draftRef.current
    if (!current) throw new Error('MEAL_DRAFT_REQUIRED')
    return runCommand('saving', async () => {
      const latest = await mealApi.getDraft(current.id)
      if (resolution === 'reload') {
        storeDraft(latest)
        const reloadedInput = draftPayloadToInput(latest.payload)
        inputRef.current = reloadedInput
        setInputState(reloadedInput)
        setStatus('idle')
        return latest
      }
      const saved = await mealApi.updateDraft(
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
    if (!current) throw new Error('MEAL_DRAFT_REQUIRED')
    return runCommand('confirming', async () => {
      confirmationKey.current ??= globalThis.crypto.randomUUID()
      const confirmed = await mealApi.confirmDraft(
        current.id,
        current.version,
        confirmationKey.current,
      )
      setConfirmedMeal(confirmed)
      setStatus('confirmed')
      return confirmed
    })
  }, [runCommand])

  const discard = useCallback(async () => {
    const current = draftRef.current
    if (current) await mealApi.deleteDraft(current.id)
    draftRef.current = null
    setDraft(null)
    confirmationKey.current = null
    setStatus('idle')
    setError(null)
  }, [])

  return {
    input,
    draft,
    confirmedMeal,
    status,
    error,
    setInput,
    save,
    resolveConflict,
    confirm,
    discard,
  }
}

function draftPayloadToInput(payload: MealDraftPayload): MealDraftCreate {
  return {
    log_date: payload.log_date,
    name: payload.name,
    meal_type: payload.meal_type,
    entry_method: 'form',
    items: payload.items.map((item) => {
      if (item.catalog_food_id) {
        return {
          catalog_food_id: item.catalog_food_id,
          amount: item.amount,
          unit: item.unit,
        }
      }
      if (!item.custom_food) throw new Error('MEAL_DRAFT_FOOD_SOURCE_REQUIRED')
      return {
        custom_food: item.custom_food,
        amount: item.amount,
        unit: item.unit,
      }
    }),
  }
}
