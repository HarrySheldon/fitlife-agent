import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api } from '../services/api'
import type { ModelConnectionInput, ModelConnectionSettings, ModelProbeResult, ModelProviderPreset, ModelWorkspace } from '../types'

const emptyForm = (): ModelConnectionInput => ({ provider_id: '', protocol: 'chat_completions', base_url: '', model: '',
  expected_revision: 0, credential_mode: 'new', api_key: '' })

function fromConnection(connection: ModelConnectionSettings, slot: 'active' | 'draft', revision: number): ModelConnectionInput {
  return { provider_id: connection.provider_id ?? connection.provider, protocol: connection.protocol,
    base_url: connection.base_url ?? (connection.provider === 'openai' ? 'https://api.openai.com/v1' : ''),
    model: connection.model, expected_revision: revision,
    credential_mode: connection.api_key_configured ? `reuse_${slot}` : 'new', api_key: '' }
}

function reconcileRevision(previous: ModelConnectionInput, workspace: ModelWorkspace): ModelConnectionInput {
  const source = previous.credential_mode === 'reuse_active' ? workspace.active : workspace.draft
  return { ...previous, expected_revision: workspace.revision,
    ...(previous.credential_mode !== 'new' && !source?.api_key_configured ? { credential_mode: 'new', api_key: '' } : {}) }
}

export function useModelSettings() {
  const { t } = useTranslation()
  const [workspace, setWorkspace] = useState<ModelWorkspace | null>(null)
  const [providers, setProviders] = useState<ModelProviderPreset[]>([])
  const [editing, setEditing] = useState<ModelConnectionInput>(emptyForm)
  const [models, setModels] = useState<string[]>([])
  const [probeResult, setProbeResult] = useState<ModelProbeResult | null>(null)
  const [verificationToken, setVerificationToken] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [dirty, setDirty] = useState(false)
  const [action, setAction] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<{ kind: 'success' | 'error'; message: string } | null>(null)
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
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [next, available] = await Promise.all([api.modelWorkspace(), api.modelProviders()])
      if (!mounted.current) return
      setWorkspace(next)
      setProviders(available.providers)
      if (!initialized.current) {
        setEditing(next.active ? fromConnection(next.active, 'active', next.revision) : { ...emptyForm(), expected_revision: next.revision })
        initialized.current = true
      } else {
        invalidate()
        setEditing(previous => reconcileRevision(previous, next))
      }
    } catch (error) {
      if (mounted.current) setFeedback({ kind: 'error', message: error instanceof Error ? error.message : t('settingsModel.requestFailed') })
    } finally {
      if (mounted.current) setLoading(false)
    }
  }, [t, invalidate])

  useEffect(() => {
    mounted.current = true
    void refresh()
    return () => { mounted.current = false; generation.current += 1; previewController.current?.abort() }
  }, [refresh])
  useEffect(() => {
    if (!verificationToken) return
    const testedAt = probeResult?.tested_at ? Date.parse(probeResult.tested_at) : Date.now()
    const remaining = Math.max(0, testedAt + 15 * 60 * 1000 - Date.now())
    const timeout = window.setTimeout(() => { setVerificationToken(null); setProbeResult(null) }, remaining)
    return () => window.clearTimeout(timeout)
  }, [verificationToken, probeResult?.tested_at])

  const patch = useCallback((changes: Partial<ModelConnectionInput>) => {
    invalidate()
    setDirty(true)
    if (changes.provider_id !== undefined || changes.base_url !== undefined
      || changes.credential_mode !== undefined || changes.api_key !== undefined) setModels([])
    setEditing(previous => {
      const targetChanged = (changes.provider_id !== undefined && changes.provider_id !== previous.provider_id)
        || (changes.base_url !== undefined && changes.base_url !== previous.base_url)
      return { ...previous, ...changes, ...(targetChanged ? { credential_mode: 'new', api_key: changes.api_key ?? '' } : {}) }
    })
  }, [invalidate])

  const load = useCallback((slot: 'active' | 'draft') => {
    const connection = workspace?.[slot]
    if (!connection || !workspace) return
    invalidate()
    setModels([])
    setEditing(fromConnection(connection, slot, workspace.revision))
    setDirty(false)
  }, [workspace, invalidate])

  async function run(name: string, operation: () => Promise<void>) {
    if (running.current) return
    running.current = true
    const id = generation.current
    setAction(name)
    setFeedback(null)
    try { await operation() }
    catch (error) {
      if (mounted.current && id === generation.current) setFeedback({ kind: 'error', message: error instanceof Error ? error.message : t('settingsModel.requestFailed') })
    } finally {
      running.current = false
      if (mounted.current) setAction(null)
    }
  }

  function payload(): ModelConnectionInput | null {
    const next = { ...editing, provider_id: editing.provider_id.trim(), base_url: editing.base_url.trim(), model: editing.model.trim() }
    if (next.credential_mode === 'new') next.api_key = next.api_key?.trim()
    else {
      delete next.api_key
      const source = workspace?.[next.credential_mode === 'reuse_active' ? 'active' : 'draft']
      const address = source?.base_url ?? 'https://api.openai.com/v1'
      if (source && ((source.provider_id ?? source.provider) !== next.provider_id || address.replace(/\/+$/, '') !== next.base_url.replace(/\/+$/, ''))) {
        if (!window.confirm(t('settingsModel.flow.confirmReuse', { from: address, to: next.base_url }))) return null
        next.confirm_credential_reuse = true
      }
    }
    return next
  }

  async function listModels() {
    if (running.current) return
    const next = payload()
    if (!next) return
    const id = generation.current
    const controller = new AbortController()
    previewController.current = controller
    await run('list', async () => {
      const result = await api.previewModels(next, controller.signal)
      if (!mounted.current || id !== generation.current) return
      setModels(result.models)
      setFeedback({ kind: 'success', message: t(result.truncated ? 'settingsModel.flow.listTruncated' : 'settingsModel.modelsLoaded', { count: result.models.length }) })
    })
    if (previewController.current === controller) previewController.current = null
  }

  async function testConnection() {
    if (running.current) return
    const next = payload()
    if (!next) return
    const id = generation.current
    const controller = new AbortController()
    previewController.current = controller
    setVerificationToken(null)
    setProbeResult(null)
    await run('test', async () => {
      const result = await api.previewModelTest(next, controller.signal)
      if (!mounted.current || id !== generation.current) return
      setProbeResult(result)
      setVerificationToken(result.status === 'success' && result.generation.status === 'passed'
        && result.structured.status === 'passed' ? result.verification_token : null)
    })
    if (previewController.current === controller) previewController.current = null
  }

  async function save(enable: boolean) {
    const next = payload()
    if (!next || (enable && !verificationToken)) return
    const id = generation.current
    await run('save', async () => {
      const result = enable ? await api.activateModel({ ...next, verification_token: verificationToken! }) : await api.saveModelDraft(next)
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
      setFeedback({ kind: 'success', message: t(enable ? 'settingsModel.flow.activated' : 'settingsModel.flow.draftSaved') })
    })
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

  return { workspace, providers, editing, patch, load, models, probeResult, verificationToken,
    loading, dirty, action, feedback, refresh, listModels, testConnection, save,
    disable: () => mutateCurrent('disable', api.disableModel),
    clearApiKey: (slot: 'active' | 'draft') => mutateCurrent('clear', revision => api.clearModelCredential(slot, revision)) }
}
