import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiRequestError, api } from '../services/api'
import type { ModelConnectionInput, ModelConnectionSettings, ModelProbeResult, ModelProviderPreset, ModelWorkspace } from '../types'

export interface UseModelSettingsOptions {
  confirmReuse?: (from: string, to: string) => Promise<boolean> | boolean
}

const emptyForm = (): ModelConnectionInput => ({
  provider_id: '',
  protocol: 'chat_completions',
  base_url: '',
  model: '',
  expected_revision: 0,
  credential_mode: 'new',
  api_key: '',
})

function fromConnection(connection: ModelConnectionSettings, slot: 'active' | 'draft', revision: number): ModelConnectionInput {
  return {
    provider_id: connection.provider_id ?? connection.provider,
    protocol: connection.protocol,
    base_url: connection.base_url ?? (connection.provider === 'openai' ? 'https://api.openai.com/v1' : ''),
    model: connection.model,
    expected_revision: revision,
    credential_mode: connection.api_key_configured ? `reuse_${slot}` : 'new',
    api_key: '',
  }
}

function fromPreset(preset: ModelProviderPreset, revision: number): ModelConnectionInput {
  return {
    provider_id: preset.id,
    protocol: preset.recommended_protocol,
    base_url: preset.default_base_url ?? '',
    model: '',
    expected_revision: revision,
    credential_mode: 'new',
    api_key: '',
  }
}

function reconcileRevision(previous: ModelConnectionInput, workspace: ModelWorkspace): ModelConnectionInput {
  const source = previous.credential_mode === 'reuse_active' ? workspace.active : workspace.draft
  return {
    ...previous,
    expected_revision: workspace.revision,
    ...(previous.credential_mode !== 'new' && !source?.api_key_configured ? { credential_mode: 'new', api_key: '' } : {}),
  }
}

function readErrorCode(error: unknown): string | null {
  if (typeof ApiRequestError === 'function' && error instanceof ApiRequestError) {
    return error.code ?? null
  }
  if (error && typeof error === 'object' && 'code' in error && typeof (error as { code?: unknown }).code === 'string') {
    return (error as { code: string }).code
  }
  return null
}

function normalizeAddress(value: string | null | undefined): string {
  return (value ?? '').trim().replace(/\/+$/, '')
}

export function useModelSettings(options?: UseModelSettingsOptions) {
  const { t } = useTranslation()
  const confirmReuseRef = useRef(options?.confirmReuse)
  confirmReuseRef.current = options?.confirmReuse

  const [workspace, setWorkspace] = useState<ModelWorkspace | null>(null)
  const [providers, setProviders] = useState<ModelProviderPreset[]>([])
  const [editing, setEditing] = useState<ModelConnectionInput>(emptyForm)
  const [models, setModels] = useState<string[]>([])
  const [probeResult, setProbeResult] = useState<ModelProbeResult | null>(null)
  const [verificationToken, setVerificationToken] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [dirty, setDirty] = useState(false)
  const [action, setAction] = useState<string | null>(null)
  const [probePhase, setProbePhase] = useState<'idle' | 'testing' | 'activating'>('idle')
  const [feedback, setFeedback] = useState<{ kind: 'success' | 'error'; message: string } | null>(null)
  const [lastErrorCode, setLastErrorCode] = useState<string | null>(null)
  const [conflictDetected, setConflictDetected] = useState(false)
  const [tokenExpiredNotice, setTokenExpiredNotice] = useState(false)
  const [justActivated, setJustActivated] = useState(false)

  const generation = useRef(0)
  const running = useRef(false)
  const initialized = useRef(false)
  const mounted = useRef(true)
  const previewController = useRef<AbortController | null>(null)

  const invalidate = useCallback(() => {
    previewController.current?.abort()
    previewController.current = null
    generation.current += 1
    setVerificationToken(null)
    setProbeResult(null)
    setFeedback(null)
    setLastErrorCode(null)
    setTokenExpiredNotice(false)
    setJustActivated(false)
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [next, available] = await Promise.all([api.modelWorkspace(), api.modelProviders()])
      if (!mounted.current) return
      setWorkspace(next)
      setProviders(available.providers)
      setConflictDetected(false)
      if (!initialized.current) {
        if (next.active) {
          setEditing(fromConnection(next.active, 'active', next.revision))
        } else if (next.draft) {
          setEditing(fromConnection(next.draft, 'draft', next.revision))
        } else if (available.providers.length > 0) {
          setEditing(fromPreset(available.providers[0], next.revision))
        } else {
          setEditing({ ...emptyForm(), expected_revision: next.revision })
        }
        initialized.current = true
      } else {
        invalidate()
        setEditing(previous => reconcileRevision(previous, next))
      }
    } catch (error) {
      if (mounted.current) {
        setLastErrorCode(readErrorCode(error))
        setFeedback({ kind: 'error', message: error instanceof Error ? error.message : t('settingsModel.requestFailed') })
      }
    } finally {
      if (mounted.current) setLoading(false)
    }
  }, [t, invalidate])

  useEffect(() => {
    mounted.current = true
    void refresh()
    return () => {
      mounted.current = false
      generation.current += 1
      previewController.current?.abort()
    }
  }, [refresh])

  useEffect(() => {
    if (!verificationToken) return
    const testedAt = probeResult?.tested_at ? Date.parse(probeResult.tested_at) : Date.now()
    const remaining = Math.max(0, testedAt + 15 * 60 * 1000 - Date.now())
    const timeout = window.setTimeout(() => {
      setVerificationToken(null)
      setProbeResult(null)
      setTokenExpiredNotice(true)
    }, remaining)
    return () => window.clearTimeout(timeout)
  }, [verificationToken, probeResult?.tested_at])

  const patch = useCallback((changes: Partial<ModelConnectionInput>) => {
    invalidate()
    setConflictDetected(false)
    setDirty(true)
    if (
      changes.provider_id !== undefined
      || changes.base_url !== undefined
      || changes.credential_mode !== undefined
      || changes.api_key !== undefined
    ) {
      setModels([])
    }
    setEditing(previous => {
      const targetChanged = (changes.provider_id !== undefined && changes.provider_id !== previous.provider_id)
        || (changes.base_url !== undefined && changes.base_url !== previous.base_url)
      return {
        ...previous,
        ...changes,
        ...(targetChanged ? { credential_mode: changes.credential_mode ?? 'new', api_key: changes.api_key ?? '' } : {}),
      }
    })
  }, [invalidate])

  const selectProvider = useCallback((providerId: string) => {
    const preset = providers.find(item => item.id === providerId)
    if (!preset) return
    invalidate()
    setConflictDetected(false)
    setModels([])

    const active = workspace?.active
    const draft = workspace?.draft
    const revision = workspace?.revision ?? editing.expected_revision

    if (active && (active.provider_id ?? active.provider) === preset.id) {
      setEditing(fromConnection(active, 'active', revision))
      setDirty(false)
      return
    }
    if (draft && (draft.provider_id ?? draft.provider) === preset.id) {
      setEditing(fromConnection(draft, 'draft', revision))
      setDirty(false)
      return
    }

    setEditing(fromPreset(preset, revision))
    setDirty(Boolean(active || draft || editing.api_key?.trim() || editing.model.trim()))
  }, [providers, workspace, editing.expected_revision, editing.api_key, editing.model, invalidate])

  const load = useCallback((slot: 'active' | 'draft') => {
    const connection = workspace?.[slot]
    if (!connection || !workspace) return
    invalidate()
    setConflictDetected(false)
    setModels([])
    setEditing(fromConnection(connection, slot, workspace.revision))
    setDirty(false)
  }, [workspace, invalidate])

  async function run<T>(name: string, operation: () => Promise<T>): Promise<T | undefined> {
    if (running.current) return undefined
    running.current = true
    const id = generation.current
    setAction(name)
    setFeedback(null)
    setLastErrorCode(null)
    try {
      return await operation()
    } catch (error) {
      if (mounted.current && id === generation.current) {
        const code = readErrorCode(error)
        setLastErrorCode(code)
        if (code === 'MODEL_CONFIGURATION_CONFLICT') setConflictDetected(true)
        setFeedback({ kind: 'error', message: error instanceof Error ? error.message : t('settingsModel.requestFailed') })
      }
      return undefined
    } finally {
      running.current = false
      if (mounted.current) {
        setAction(null)
        setProbePhase('idle')
      }
    }
  }

  function preparePayload(): { payload: ModelConnectionInput; needsConfirm?: { from: string; to: string } } {
    const next: ModelConnectionInput = {
      ...editing,
      provider_id: editing.provider_id.trim(),
      base_url: editing.base_url.trim(),
      model: editing.model.trim(),
    }
    if (next.credential_mode === 'new') {
      next.api_key = next.api_key?.trim()
      return { payload: next }
    }
    delete next.api_key
    const source = workspace?.[next.credential_mode === 'reuse_active' ? 'active' : 'draft']
    const address = source?.base_url ?? 'https://api.openai.com/v1'
    if (
      source
      && (
        (source.provider_id ?? source.provider) !== next.provider_id
        || normalizeAddress(address) !== normalizeAddress(next.base_url)
      )
    ) {
      return { payload: next, needsConfirm: { from: address, to: next.base_url } }
    }
    return { payload: next }
  }

  async function confirmCrossHostReuse(from: string, to: string): Promise<boolean> {
    if (confirmReuseRef.current) {
      return Boolean(await confirmReuseRef.current(from, to))
    }
    return window.confirm(t('settingsModel.flow.confirmReuse', { from, to }))
  }

  async function listModels(): Promise<boolean> {
    if (running.current) return false
    const id = generation.current
    const prepared = preparePayload()
    const next = prepared.payload
    if (prepared.needsConfirm) {
      const approved = await confirmCrossHostReuse(prepared.needsConfirm.from, prepared.needsConfirm.to)
      if (!approved || !mounted.current || id !== generation.current) return false
      next.confirm_credential_reuse = true
    }
    const controller = new AbortController()
    previewController.current = controller
    const ok = await run('list', async () => {
      const result = await api.previewModels(next, controller.signal)
      if (!mounted.current || id !== generation.current) return false
      setModels(result.models)
      setFeedback({
        kind: 'success',
        message: t(result.truncated ? 'settingsModel.flow.listTruncated' : 'settingsModel.modelsLoaded', { count: result.models.length }),
      })
      return true
    })
    if (previewController.current === controller) previewController.current = null
    return Boolean(ok)
  }

  async function testConnection() {
    if (running.current) return
    const id = generation.current
    const prepared = preparePayload()
    const next = prepared.payload
    if (prepared.needsConfirm) {
      const approved = await confirmCrossHostReuse(prepared.needsConfirm.from, prepared.needsConfirm.to)
      if (!approved || !mounted.current || id !== generation.current) return
      next.confirm_credential_reuse = true
    }
    const controller = new AbortController()
    previewController.current = controller
    setVerificationToken(null)
    setProbeResult(null)
    setTokenExpiredNotice(false)
    setJustActivated(false)
    await run('test', async () => {
      setProbePhase('testing')
      const result = await api.previewModelTest(next, controller.signal)
      if (!mounted.current || id !== generation.current) return
      setProbeResult(result)
      setVerificationToken(
        result.status === 'success'
        && result.generation.status === 'passed'
        && result.structured.status === 'passed'
          ? result.verification_token
          : null,
      )
    })
    if (previewController.current === controller) previewController.current = null
  }

  async function save(enable: boolean) {
    if (running.current) return
    if (enable && !verificationToken) return
    const id = generation.current
    const prepared = preparePayload()
    const next = prepared.payload
    if (prepared.needsConfirm) {
      const approved = await confirmCrossHostReuse(prepared.needsConfirm.from, prepared.needsConfirm.to)
      if (!approved || !mounted.current || id !== generation.current) return
      next.confirm_credential_reuse = true
    }
    await run('save', async () => {
      const result = enable
        ? await api.activateModel({ ...next, verification_token: verificationToken! })
        : await api.saveModelDraft(next)
      if (!mounted.current) return
      setWorkspace(result)
      invalidate()
      if (id + 1 === generation.current) {
        const saved = enable ? result.active : result.draft
        if (saved) setEditing(fromConnection(saved, enable ? 'active' : 'draft', result.revision))
        setDirty(false)
      } else {
        setEditing(previous => reconcileRevision(previous, result))
      }
      if (enable) setJustActivated(true)
      setFeedback({ kind: 'success', message: t(enable ? 'settingsModel.flow.activated' : 'settingsModel.flow.draftSaved') })
    })
  }

  async function testAndEnable() {
    if (running.current) return
    const id = generation.current
    const prepared = preparePayload()
    const next = prepared.payload
    if (prepared.needsConfirm) {
      const approved = await confirmCrossHostReuse(prepared.needsConfirm.from, prepared.needsConfirm.to)
      if (!approved || !mounted.current || id !== generation.current) return
      next.confirm_credential_reuse = true
    }
    const controller = new AbortController()
    previewController.current = controller
    setTokenExpiredNotice(false)
    setJustActivated(false)
    await run('test_and_enable', async () => {
      let tokenToUse = verificationToken
      if (!tokenToUse) {
        setProbeResult(null)
        setProbePhase('testing')
        const probe = await api.previewModelTest(next, controller.signal)
        if (!mounted.current || id !== generation.current) return
        setProbeResult(probe)
        tokenToUse = (
          probe.status === 'success'
          && probe.generation.status === 'passed'
          && probe.structured.status === 'passed'
            ? probe.verification_token
            : null
        )
        setVerificationToken(tokenToUse)
        if (!tokenToUse) return
      }

      if (!mounted.current || id !== generation.current) return
      setProbePhase('activating')
      const result = await api.activateModel({ ...next, verification_token: tokenToUse })
      if (!mounted.current) return
      setWorkspace(result)
      invalidate()
      if (id + 1 === generation.current) {
        if (result.active) setEditing(fromConnection(result.active, 'active', result.revision))
        setDirty(false)
      } else {
        setEditing(previous => reconcileRevision(previous, result))
      }
      setJustActivated(true)
      setFeedback({ kind: 'success', message: t('settingsModel.flow.activated') })
    })
    if (previewController.current === controller) previewController.current = null
  }

  async function mutateCurrent(name: string, operation: (revision: number) => Promise<ModelWorkspace>) {
    if (!workspace) return
    await run(name, async () => {
      const result = await operation(workspace.revision)
      if (!mounted.current) return
      setWorkspace(result)
      invalidate()
      setEditing(previous => reconcileRevision(previous, result))
    })
  }

  return {
    workspace,
    providers,
    editing,
    patch,
    selectProvider,
    load,
    models,
    probeResult,
    verificationToken,
    loading,
    dirty,
    action,
    probePhase,
    feedback,
    lastErrorCode,
    conflictDetected,
    tokenExpiredNotice,
    justActivated,
    refresh,
    listModels,
    testConnection,
    testAndEnable,
    save,
    disable: () => mutateCurrent('disable', api.disableModel),
    clearApiKey: (slot: 'active' | 'draft') => mutateCurrent('clear', revision => api.clearModelCredential(slot, revision)),
  }
}
