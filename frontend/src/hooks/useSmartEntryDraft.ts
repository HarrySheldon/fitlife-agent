import { useCallback, useEffect, useRef, useState } from 'react'
import { smartEntryApi } from '../services/smartEntryApi'
import { commandFingerprint, onSmartEntryLogout, recoveryGeneration, recoveryOwner, removeRecovery } from '../services/smartEntryRecovery'
import type { ConfirmedSmartEntry, PendingSmartEntryConfirmation, SmartEntryCreate, SmartEntryDraft, SmartEntryDraftPayload, EntryAnswer, EntryUpdates, EntrySelection } from '../types/smartEntry'

export type SmartEntryStatus = 'idle' | 'restoring' | 'parsing' | 'saving' | 'analyzing' | 'confirming' | 'conflict' | 'error'
type DraftSource = 'server' | 'training_save'
export function useSmartEntryDraft(recoveryKey: string) {
  const [draftState, setDraftState] = useState<{ key: string; value: SmartEntryDraft | null; source: DraftSource }>({ key: recoveryKey, value: null, source: 'server' })
  const draft = draftState.key === recoveryKey ? draftState.value : null
  const setDraft = (value: SmartEntryDraft | null, source: DraftSource = 'server') => setDraftState({ key: scope.current.key, value, source })
  const [confirmed, setConfirmed] = useState<ConfirmedSmartEntry | null>(null)
  const [status, setStatus] = useState<SmartEntryStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const scope = useRef({ key: recoveryKey, epoch: 0 })
  const draftRef = useRef<SmartEntryDraft | null>(null)
  const commandActive = useRef(false)
  const pendingRef = useRef<PendingSmartEntryConfirmation | null>(null)
  if (scope.current.key !== recoveryKey) {
    scope.current = { key: recoveryKey, epoch: scope.current.epoch + 1 }
    draftRef.current = null; pendingRef.current = null; commandActive.current = false
  }
  useEffect(() => {
    setDraft(null); setConfirmed(null); setError(null); setStatus('idle')
  }, [recoveryKey])
  useEffect(() => () => {
    scope.current.epoch += 1
    commandActive.current = false
  }, [])
  useEffect(() => onSmartEntryLogout((owner) => {
    if (recoveryOwner(scope.current.key) !== owner) return
    scope.current.epoch += 1
    draftRef.current = null; pendingRef.current = null; commandActive.current = false
    setDraft(null); setConfirmed(null); setError(null); setStatus('idle')
  }), [])
  const run = useCallback(async <T,>(nextStatus: SmartEntryStatus, command: (valid: () => boolean, publish: (next: SmartEntryDraft | null, source?: DraftSource) => void) => Promise<T>) => {
    if (commandActive.current) throw new Error('SMART_ENTRY_OPERATION_IN_PROGRESS')
    const { key, epoch } = scope.current
    const owner = recoveryOwner(key)
    const generation = recoveryGeneration(owner)
    const valid = () => scope.current.key === key && scope.current.epoch === epoch && recoveryGeneration(owner) === generation
    const publish = (next: SmartEntryDraft | null, source: DraftSource = 'server') => {
      if (!valid()) return
      if (next && owner && next.user_id !== owner) throw new Error('SMART_ENTRY_OWNER_MISMATCH')
      draftRef.current = next; setDraft(next, source)
    }
    commandActive.current = true; setStatus(nextStatus); setError(null)
    try {
      const result = await command(valid, publish)
      if (!valid()) throw new Error('SMART_ENTRY_SCOPE_CHANGED')
      setStatus('idle'); return result
    } catch (cause) {
      if (valid()) {
        const conflict = typeof cause === 'object' && cause !== null && 'status' in cause && cause.status === 409
        if (conflict && draftRef.current) {
          try { publish(await smartEntryApi.getDraft(draftRef.current.id)) } catch { /* Retain visible draft for review. */ }
          if (valid()) { pendingRef.current = null; removeRecovery(key) }
        }
        if (valid()) {
          setStatus(conflict ? 'conflict' : 'error')
          setError(typeof cause === 'object' && cause !== null && 'status' in cause && cause.status === 404
            ? 'SMART_ENTRY_TASK_UNAVAILABLE' : cause instanceof Error ? cause.message : 'SMART_ENTRY_FAILED')
        }
      }
      throw cause
    } finally { if (valid()) commandActive.current = false }
  }, [])
  const restore = useCallback((logDate: string) => run('restoring', async (valid, publish) => {
    const pending = readPending(recoveryKey)
    if (valid()) pendingRef.current = pending?.fingerprint ? pending : null
    const restored = pending ? await smartEntryApi.getDraft(pending.taskId) : await smartEntryApi.findLatestDraft(logDate)
    if (restored && restored.payload.log_date !== logDate) throw new Error('SMART_ENTRY_DATE_MISMATCH')
    publish(restored); return restored
  }), [recoveryKey, run])
  const parse = useCallback((input: SmartEntryCreate) => run('parsing', async (valid, publish) => {
    const created = await smartEntryApi.createDraft(input)
    if (valid()) { pendingRef.current = null; removeRecovery(recoveryKey) }
    publish(created); return created
  }), [recoveryKey, run])
  const save = useCallback((payload: SmartEntryDraftPayload) => run('saving', async (_valid, publish) => {
    const current = required(draftRef.current)
    if (current.payload.interaction?.active && !trainingOnlyUpdate(current.payload, payload)) throw new Error('SMART_ENTRY_ACTIVE_USE_ITEM_CORRECTIONS')
    const saved = await smartEntryApi.updateDraft(current.id, current.version, payload)
    publish(saved, current.payload.interaction?.active ? 'training_save' : 'server'); return saved
  }), [run])
  const analyze = useCallback(async (payload: SmartEntryDraftPayload) => {
    if (required(draftRef.current).payload.interaction?.active) throw new Error('SMART_ENTRY_ACTIVE_USE_ITEM_CORRECTIONS')
    const initialKey = scope.current.key
    const initialEpoch = scope.current.epoch
    const initialGeneration = recoveryGeneration(recoveryOwner(initialKey))
    const saved = await save(payload)
    if (scope.current.key !== initialKey || scope.current.epoch !== initialEpoch || recoveryGeneration(recoveryOwner(initialKey)) !== initialGeneration) throw new Error('SMART_ENTRY_SCOPE_CHANGED')
    return run('analyzing', async (_valid, publish) => {
      const analyzed = await smartEntryApi.analyzeDraft(saved.id, saved.version)
      publish(analyzed); return analyzed
    })
  }, [run, save])
  const confirm = useCallback(async (payload: SmartEntryDraftPayload) => {
    const initialKey = scope.current.key
    const initialEpoch = scope.current.epoch
    const initialGeneration = recoveryGeneration(recoveryOwner(initialKey))
    let current = required(draftRef.current)
    const active = current.payload.interaction?.active
    let body = mutationPayload(payload)
    const fingerprint = await commandFingerprint({ kind: 'legacy-confirm', version: current.version, body })
    if (scope.current.key !== initialKey || scope.current.epoch !== initialEpoch || recoveryGeneration(recoveryOwner(initialKey)) !== initialGeneration) throw new Error('SMART_ENTRY_SCOPE_CHANGED')
    const existing = pendingRef.current ?? readPending(recoveryKey)
    if (!existing && (!active || !sameValue(body, mutationPayload(current.payload)))) {
      current = await save(payload)
      if (active) body = mutationPayload(current.payload)
    }
    if (scope.current.key !== initialKey || scope.current.epoch !== initialEpoch || recoveryGeneration(recoveryOwner(initialKey)) !== initialGeneration) throw new Error('SMART_ENTRY_SCOPE_CHANGED')
    return run('confirming', async (valid, publish) => {
      const hash = await commandFingerprint({ kind: 'legacy-confirm', version: current.version, body })
      if (existing && existing.fingerprint !== fingerprint) throw conflictError()
      if (!valid()) throw new Error('SMART_ENTRY_SCOPE_CHANGED')
      const pending = existing ?? { taskId: current.id, idempotencyKey: crypto.randomUUID(), fingerprint: hash }
      pendingRef.current = pending; writePending(recoveryKey, pending)
      const result = await smartEntryApi.confirmDraft(current.id, current.version, pending.idempotencyKey)
      if (!valid()) throw new Error('SMART_ENTRY_SCOPE_CHANGED')
      if (valid()) { pendingRef.current = null; removeRecovery(recoveryKey); setConfirmed(result) }
      if (active) publish(await smartEntryApi.getDraft(current.id))
      return result
    })
  }, [recoveryKey, run, save])
  const interactionCommand = useCallback((kind: string, body: unknown, request: (current: SmartEntryDraft, key: string) => Promise<unknown>, refresh = false) => run('saving', async (valid, publish) => {
    const current = required(draftRef.current)
    const fingerprint = await commandFingerprint({ kind, version: current.version, body })
    const existing = pendingRef.current ?? readPending(recoveryKey)
    if (existing && existing.fingerprint !== fingerprint) throw conflictError()
    if (!valid()) throw new Error('SMART_ENTRY_SCOPE_CHANGED')
    const pending = existing ?? { taskId: current.id, idempotencyKey: crypto.randomUUID(), fingerprint }
    pendingRef.current = pending; writePending(recoveryKey, pending)
    const response = await request(current, pending.idempotencyKey)
    if (!valid()) throw new Error('SMART_ENTRY_SCOPE_CHANGED')
    const next = refresh ? await smartEntryApi.getDraft(current.id) : response as SmartEntryDraft
    publish(next)
    if (valid()) { pendingRef.current = null; removeRecovery(recoveryKey) }
    return next
  }), [recoveryKey, run])
  const startInteraction = useCallback(() => interactionCommand('start', {}, (current, key) => smartEntryApi.startInteraction(current.id, current.version, key)), [interactionCommand])
  const answerInteraction = useCallback((groupId: string, answers: EntryAnswer[]) => interactionCommand('answers', { groupId, answers }, (current, key) => smartEntryApi.answerInteraction(current.id, current.version, key, groupId, answers)), [interactionCommand])
  const correctItem = useCallback((itemId: string, revision: number, updates: EntryUpdates) => interactionCommand('correction', { itemId, revision, updates }, (current, key) => smartEntryApi.correctInteraction(current.id, current.version, key, itemId, revision, updates)), [interactionCommand])
  const confirmItems = useCallback((selections: EntrySelection[], estimates: EntrySelection[]) => interactionCommand('confirm-items', { selections, estimates }, (current, key) => smartEntryApi.confirmItems(current.id, current.version, key, selections, estimates), true), [interactionCommand])
  const discard = useCallback(() => run('saving', async (valid, publish) => {
    const current = draftRef.current
    if (current) await smartEntryApi.deleteDraft(current.id)
    if (valid()) { pendingRef.current = null; removeRecovery(recoveryKey) }
    publish(null)
  }), [recoveryKey, run])
  const currentScope = draftState.key === recoveryKey
  return { draft, draftSource: currentScope ? draftState.source : 'server' as DraftSource, confirmed: currentScope ? confirmed : null, status: currentScope ? status : 'idle' as SmartEntryStatus, error: currentScope ? error : null, restore, parse, save, analyze, confirm, discard, startInteraction, answerInteraction, correctItem, confirmItems }
}
function required(draft: SmartEntryDraft | null) {
  if (!draft) throw new Error('SMART_ENTRY_DRAFT_REQUIRED')
  return draft
}
function mutationPayload(payload: SmartEntryDraftPayload) {
  return { log_date: payload.log_date, raw_text: payload.raw_text, parser_version: payload.parser_version, candidates: payload.candidates }
}
function trainingOnlyUpdate(current: SmartEntryDraftPayload, next: SmartEntryDraftPayload) {
  if (current.log_date !== next.log_date || current.raw_text !== next.raw_text || current.parser_version !== next.parser_version
    || current.candidates.length !== next.candidates.length
    || !current.candidates.some((item) => item.kind === 'strength' || item.kind === 'cardio')) return false
  const identity = (item: SmartEntryDraftPayload['candidates'][number]) => ({
    id: item.id, kind: item.kind, raw_text: item.raw_text, normalized_text: item.normalized_text,
    subject_text: item.subject_text, meal_context: item.meal_context, catalog_choices: item.catalog_choices, assumptions: item.assumptions,
  })
  return current.candidates.every((item, index) => {
    const proposed = next.candidates[index]
    return item.kind === 'strength' || item.kind === 'cardio'
      ? sameValue(identity(item), identity(proposed)) : sameValue(item, proposed)
  })
}
function sameValue(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object' || Array.isArray(left) !== Array.isArray(right)) return false
  const a = Object.entries(left).sort(([key], [other]) => key.localeCompare(other))
  const b = Object.entries(right).sort(([key], [other]) => key.localeCompare(other))
  return a.length === b.length && a.every(([key, value], index) => key === b[index][0] && sameValue(value, b[index][1]))
}
function conflictError() { return Object.assign(new Error('SMART_ENTRY_RECOVERY_REVIEW_REQUIRED'), { status: 409 }) }
function readPending(key: string): PendingSmartEntryConfirmation | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const value = JSON.parse(raw)
    if (value.draft) {
      removeRecovery(key)
      return typeof value.draft.id === 'string' ? { taskId: value.draft.id, idempotencyKey: '', fingerprint: '' } : null
    }
    if (typeof value.taskId === 'string' && typeof value.idempotencyKey === 'string' && /^[a-f0-9]{64}$/.test(value.fingerprint)) {
      const reference = { taskId: value.taskId, idempotencyKey: value.idempotencyKey, fingerprint: value.fingerprint }
      writePending(key, reference); return reference
    }
    removeRecovery(key)
  } catch { removeRecovery(key) }
  return null
}
function writePending(key: string, pending: PendingSmartEntryConfirmation) {
  try { localStorage.setItem(key, JSON.stringify({ taskId: pending.taskId, idempotencyKey: pending.idempotencyKey, fingerprint: pending.fingerprint })) }
  catch { /* A completed server save must not fail because browser storage is unavailable. */ }
}
