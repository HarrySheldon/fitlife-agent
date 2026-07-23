import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiRequestError, api } from '../services/api'
import type {
  DailyTargetValues,
  OverallGoalVersionUpdate,
  ProfileSetup,
  ProfileSetupMutation,
  ProfileVersionUpdate,
  TargetPreview,
} from '../types'


export function useProfileSetup() {
  const setupReadSequence = useRef(0)
  const activeCommand = useRef<{
    kind: 'saving' | 'calculating' | 'confirming'
    owner: symbol
  } | null>(null)
  const confirmationAttempt = useRef<{
    fingerprint: string
    idempotencyKey: string
  } | null>(null)
  const [setup, setSetup] = useState<ProfileSetup | null>(null)
  const [preview, setPreview] = useState<TargetPreview | null>(null)
  const [restriction, setRestriction] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [calculating, setCalculating] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [stalePreview, setStalePreview] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const clearConfirmationAttempt = useCallback(() => {
    confirmationAttempt.current = null
  }, [])

  const invalidateSetupReads = useCallback(() => {
    setupReadSequence.current += 1
    setLoading(false)
  }, [])

  const beginCommand = useCallback((
    kind: 'saving' | 'calculating' | 'confirming',
  ) => {
    if (activeCommand.current) {
      throw new Error('PROFILE_SETUP_OPERATION_IN_PROGRESS')
    }

    const owner = Symbol(kind)
    activeCommand.current = { kind, owner }
    invalidateSetupReads()
    if (kind === 'saving') setSaving(true)
    if (kind === 'calculating') setCalculating(true)
    if (kind === 'confirming') setConfirming(true)
    setError(null)
    return owner
  }, [invalidateSetupReads])

  const endCommand = useCallback((
    kind: 'saving' | 'calculating' | 'confirming',
    owner: symbol,
  ) => {
    if (activeCommand.current?.owner !== owner) return

    activeCommand.current = null
    if (kind === 'saving') setSaving(false)
    if (kind === 'calculating') setCalculating(false)
    if (kind === 'confirming') setConfirming(false)
  }, [])

  const refresh = useCallback(async () => {
    const sequence = setupReadSequence.current + 1
    setupReadSequence.current = sequence
    setLoading(true)
    setError(null)
    try {
      const loaded = await api.profileSetup()
      if (setupReadSequence.current === sequence) {
        setSetup(loaded)
        setStalePreview(false)
      }
      return loaded
    } catch (cause) {
      if (setupReadSequence.current === sequence) {
        setError((cause as Error).message)
      }
      throw cause
    } finally {
      if (setupReadSequence.current === sequence) setLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const sequence = setupReadSequence.current + 1
    setupReadSequence.current = sequence
    setLoading(true)
    setError(null)
    api.profileSetup()
      .then((loaded) => {
        if (!cancelled && setupReadSequence.current === sequence) {
          setSetup(loaded)
        }
      })
      .catch((cause: Error) => {
        if (!cancelled && setupReadSequence.current === sequence) {
          setError(cause.message)
        }
      })
      .finally(() => {
        if (!cancelled && setupReadSequence.current === sequence) {
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const applyMutation = useCallback((
    mutation: ProfileSetupMutation,
  ) => {
    invalidateSetupReads()
    setSetup((current) => ({
      profile: mutation.profile,
      goal: mutation.goal,
      target: current?.target ?? null,
      setup_complete: Boolean(mutation.profile && mutation.goal && current?.target),
    }))
    setPreview(mutation.recalculation_preview)
    setRestriction(mutation.recalculation_restriction)
    setStalePreview(false)
    clearConfirmationAttempt()
  }, [clearConfirmationAttempt, invalidateSetupReads])

  const updateProfile = useCallback(async (update: ProfileVersionUpdate) => {
    const owner = beginCommand('saving')
    try {
      const mutation = await api.saveProfileVersion(update)
      applyMutation(mutation)
      return mutation
    } catch (cause) {
      setError((cause as Error).message)
      throw cause
    } finally {
      endCommand('saving', owner)
    }
  }, [applyMutation, beginCommand, endCommand])

  const updateOverallGoal = useCallback(async (update: OverallGoalVersionUpdate) => {
    const owner = beginCommand('saving')
    try {
      const mutation = await api.saveOverallGoal(update)
      applyMutation(mutation)
      return mutation
    } catch (cause) {
      setError((cause as Error).message)
      throw cause
    } finally {
      endCommand('saving', owner)
    }
  }, [applyMutation, beginCommand, endCommand])

  const calculateTargets = useCallback(async (manualTargets?: DailyTargetValues) => {
    const owner = beginCommand('calculating')
    try {
      const calculated = await api.calculateTargets(manualTargets)
      setPreview(calculated)
      setRestriction(null)
      setStalePreview(false)
      clearConfirmationAttempt()
      return calculated
    } catch (cause) {
      setError((cause as Error).message)
      throw cause
    } finally {
      endCommand('calculating', owner)
    }
  }, [beginCommand, clearConfirmationAttempt, endCommand])

  const confirmTargets = useCallback(async ({
    effectiveFrom,
    acknowledgeWarnings,
  }: {
    effectiveFrom: string
    acknowledgeWarnings: boolean
  }) => {
    const owner = beginCommand('confirming')
    try {
      if (!preview) throw new Error('TARGET_PREVIEW_REQUIRED')
      const fingerprint = confirmationFingerprint(
        preview,
        effectiveFrom,
        acknowledgeWarnings,
      )
      if (confirmationAttempt.current?.fingerprint !== fingerprint) {
        confirmationAttempt.current = {
          fingerprint,
          idempotencyKey: globalThis.crypto.randomUUID(),
        }
      }
      const attempt = confirmationAttempt.current
      const confirmation = await api.confirmTargets({
        preview,
        effective_from: effectiveFrom,
        acknowledge_warnings: acknowledgeWarnings,
        idempotencyKey: attempt.idempotencyKey,
      })
      const sequence = setupReadSequence.current + 1
      setupReadSequence.current = sequence
      const loaded = await api.profileSetup()
      if (setupReadSequence.current === sequence) {
        setSetup(loaded)
      }
      setPreview(null)
      setRestriction(null)
      setStalePreview(false)
      if (confirmationAttempt.current === attempt) clearConfirmationAttempt()
      return confirmation.target
    } catch (cause) {
      if (
        cause instanceof ApiRequestError
        && (cause.code === 'TARGET_PREVIEW_STALE' || cause.status === 412)
      ) {
        setPreview(null)
        setStalePreview(true)
        clearConfirmationAttempt()
      }
      setError((cause as Error).message)
      throw cause
    } finally {
      endCommand('confirming', owner)
    }
  }, [beginCommand, clearConfirmationAttempt, endCommand, preview])

  return {
    setup,
    preview,
    restriction,
    loading,
    saving,
    calculating,
    confirming,
    stalePreview,
    error,
    refresh,
    updateProfile,
    updateOverallGoal,
    calculateTargets,
    confirmTargets,
  }
}

function confirmationFingerprint(
  preview: TargetPreview,
  effectiveFrom: string,
  acknowledgeWarnings: boolean,
): string {
  return JSON.stringify([
    preview.profile_version_id,
    preview.overall_goal_version_id,
    preview.targets.calories,
    preview.targets.carbs,
    preview.targets.protein,
    preview.targets.fat,
    preview.source,
    preview.formula_version,
    preview.warnings,
    preview.requires_confirmation,
    preview.preview_token,
    effectiveFrom,
    acknowledgeWarnings,
  ])
}
