import { useCallback, useRef, useState } from 'react'

import { smartEntryApi } from '../services/smartEntryApi'
import type {
  ConfirmedSmartEntry,
  PendingSmartEntryConfirmation,
  SmartEntryCreate,
  SmartEntryDraft,
  SmartEntryDraftPayload,
} from '../types/smartEntry'


export type SmartEntryStatus =
  | 'idle'
  | 'restoring'
  | 'parsing'
  | 'saving'
  | 'analyzing'
  | 'confirming'
  | 'conflict'
  | 'error'

export function useSmartEntryDraft(recoveryKey: string) {
  const [draft, setDraftState] = useState<SmartEntryDraft | null>(null)
  const draftRef = useRef<SmartEntryDraft | null>(null)
  const [confirmed, setConfirmed] = useState<ConfirmedSmartEntry | null>(null)
  const [status, setStatus] = useState<SmartEntryStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const commandActive = useRef(false)
  const pendingRef = useRef<PendingSmartEntryConfirmation | null>(null)

  const storeDraft = useCallback((next: SmartEntryDraft | null) => {
    draftRef.current = next
    setDraftState(next)
  }, [])

  const run = useCallback(async <T,>(
    nextStatus: Exclude<SmartEntryStatus, 'idle' | 'conflict' | 'error'>,
    command: () => Promise<T>,
  ) => {
    if (commandActive.current) throw new Error('SMART_ENTRY_OPERATION_IN_PROGRESS')
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
        && 'code' in cause
        && cause.code === 'DRAFT_VERSION_CONFLICT'
      )
      setStatus(conflict ? 'conflict' : 'error')
      setError((cause as Error).message)
      throw cause
    } finally {
      commandActive.current = false
    }
  }, [])

  const restore = useCallback(async (logDate: string) => (
    run('restoring', async () => {
      const pending = readPending(recoveryKey)
      if (pending) {
        pendingRef.current = pending
        storeDraft(pending.draft)
        setStatus('idle')
        return pending.draft
      }
      const restored = await smartEntryApi.findLatestDraft(logDate)
      storeDraft(restored)
      setStatus('idle')
      return restored
    })
  ), [recoveryKey, run, storeDraft])

  const parse = useCallback(async (input: SmartEntryCreate) => (
    run('parsing', async () => {
      const created = await smartEntryApi.createDraft(input)
      pendingRef.current = null
      clearPending(recoveryKey)
      storeDraft(created)
      setStatus('idle')
      return created
    })
  ), [recoveryKey, run, storeDraft])

  const save = useCallback(async (payload: SmartEntryDraftPayload) => {
    const current = draftRef.current
    if (!current) throw new Error('SMART_ENTRY_DRAFT_REQUIRED')
    return run('saving', async () => {
      const saved = await smartEntryApi.updateDraft(
        current.id,
        current.version,
        payload,
      )
      storeDraft(saved)
      setStatus('idle')
      return saved
    })
  }, [run, storeDraft])

  const analyze = useCallback(async (payload: SmartEntryDraftPayload) => {
    const saved = await save(payload)
    return run('analyzing', async () => {
      const analyzed = await smartEntryApi.analyzeDraft(
        saved.id,
        saved.version,
      )
      storeDraft(analyzed)
      setStatus('idle')
      return analyzed
    })
  }, [run, save, storeDraft])

  const confirm = useCallback(async (payload: SmartEntryDraftPayload) => {
    const fingerprint = JSON.stringify(payload)
    let pending = pendingRef.current ?? readPending(recoveryKey)
    if (!pending || pending.fingerprint !== fingerprint) {
      const saved = await save(payload)
      pending = {
        draft: saved,
        idempotencyKey: globalThis.crypto.randomUUID(),
        fingerprint,
      }
      pendingRef.current = pending
      writePending(recoveryKey, pending)
    }
    return run('confirming', async () => {
      const result = await smartEntryApi.confirmDraft(
        pending.draft.id,
        pending.draft.version,
        pending.idempotencyKey,
      )
      pendingRef.current = null
      clearPending(recoveryKey)
      setConfirmed(result)
      setStatus('idle')
      return result
    })
  }, [recoveryKey, run, save])

  const discard = useCallback(async () => {
    const current = draftRef.current
    if (current) await smartEntryApi.deleteDraft(current.id)
    pendingRef.current = null
    clearPending(recoveryKey)
    storeDraft(null)
    setStatus('idle')
    setError(null)
  }, [recoveryKey, storeDraft])

  return {
    draft,
    confirmed,
    status,
    error,
    restore,
    parse,
    save,
    analyze,
    confirm,
    discard,
  }
}

function readPending(key: string): PendingSmartEntryConfirmation | null {
  try {
    const raw = globalThis.localStorage.getItem(key)
    return raw ? JSON.parse(raw) as PendingSmartEntryConfirmation : null
  } catch {
    return null
  }
}

function writePending(
  key: string,
  pending: PendingSmartEntryConfirmation,
) {
  globalThis.localStorage.setItem(key, JSON.stringify(pending))
}

function clearPending(key: string) {
  globalThis.localStorage.removeItem(key)
}
