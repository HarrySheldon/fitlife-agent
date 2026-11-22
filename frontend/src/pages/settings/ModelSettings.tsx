import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  Eye,
  EyeOff,
  FlaskConical,
  KeyRound,
  RefreshCw,
  Save,
  Sparkles,
  XCircle,
  Zap,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'

import { ConfirmModal } from '../../components/ConfirmModal'
import { useModelSettings } from '../../hooks/useModelSettings'
import type { ModelProtocol, ModelProviderPreset } from '../../types'
import { UnsavedModelChanges } from './UnsavedModelChanges'

const DIAGNOSTIC_KEYS: Record<string, string> = {
  MODEL_AUTH_FAILED: 'settingsModel.flow.diagnostics.MODEL_AUTH_FAILED',
  MODEL_NOT_FOUND: 'settingsModel.flow.diagnostics.MODEL_NOT_FOUND',
  MODEL_TIMEOUT: 'settingsModel.flow.diagnostics.MODEL_TIMEOUT',
  MODEL_QUOTA_EXHAUSTED: 'settingsModel.flow.diagnostics.MODEL_QUOTA_EXHAUSTED',
  MODEL_RATE_LIMITED: 'settingsModel.flow.diagnostics.MODEL_RATE_LIMITED',
  INVALID_MODEL_ENDPOINT: 'settingsModel.flow.diagnostics.INVALID_MODEL_ENDPOINT',
  MODEL_PROTOCOL_ERROR: 'settingsModel.flow.diagnostics.MODEL_PROTOCOL_ERROR',
  MODEL_LIST_UNAVAILABLE: 'settingsModel.flow.diagnostics.MODEL_LIST_UNAVAILABLE',
  CREDENTIAL_STORE_UNAVAILABLE: 'settingsModel.flow.diagnostics.CREDENTIAL_STORE_UNAVAILABLE',
  STRUCTURED_FAILED: 'settingsModel.flow.diagnostics.STRUCTURED_FAILED',
}

const PRESET_LABEL_KEYS: Record<string, string> = {
  deepseek: 'settingsModel.presets.deepseek',
  openai: 'settingsModel.presets.openai',
  dashscope: 'settingsModel.presets.dashscope',
  siliconflow: 'settingsModel.presets.siliconflow',
  openrouter: 'settingsModel.presets.openrouter',
  moonshot: 'settingsModel.presets.moonshot',
  custom: 'settingsModel.presets.custom',
}

function isPrivateOrLocalHost(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, '')
  if (
    host === 'localhost'
    || host.endsWith('.localhost')
    || host === '::1'
    || host === '0.0.0.0'
    || host.startsWith('127.')
    || host.startsWith('10.')
    || host.startsWith('192.168.')
    || host.startsWith('169.254.')
  ) {
    return true
  }
  const match172 = /^172\.(\d{1,3})\./.exec(host)
  if (match172) {
    const second = Number(match172[1])
    if (second >= 16 && second <= 31) return true
  }
  return false
}

function validateEndpointUrl(raw: string): 'urlHttpsOnly' | 'urlInvalid' | null {
  const trimmed = raw.trim()
  if (!trimmed) return null
  try {
    const parsed = new URL(trimmed)
    if (parsed.protocol !== 'https:') return 'urlHttpsOnly'
    if (!parsed.hostname) return 'urlInvalid'
    if (isPrivateOrLocalHost(parsed.hostname)) return 'urlHttpsOnly'
    return null
  } catch {
    if (/^http:\/\//i.test(trimmed) || /^(localhost|127\.0\.0\.1)/i.test(trimmed)) {
      return 'urlHttpsOnly'
    }
    return 'urlInvalid'
  }
}

function safeInternalPath(raw: string | null): string | null {
  if (!raw) return null
  const trimmed = raw.trim()
  if (!trimmed.startsWith('/') || trimmed.startsWith('//')) return null
  return trimmed
}

interface ConfirmDialogConfig {
  title: string
  message: string
  confirmLabel: string
  cancelLabel: string
  tone?: 'primary' | 'danger'
  onConfirm: () => void
  onCancel?: () => void
}

export function ModelSettings() {
  const { t } = useTranslation()
  const [searchParams] = useSearchParams()
  const returnTo = safeInternalPath(searchParams.get('returnTo'))

  const [confirmDialog, setConfirmDialog] = useState<ConfirmDialogConfig | null>(null)
  const [keyVisible, setKeyVisible] = useState(false)
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false)
  const [filteringModels, setFilteringModels] = useState(false)
  const [urlTouched, setUrlTouched] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)

  const modelInputRef = useRef<HTMLInputElement>(null)
  const comboboxRef = useRef<HTMLDivElement>(null)

  const confirmReuse = useCallback((from: string, to: string): Promise<boolean> => {
    return new Promise((resolve) => {
      setConfirmDialog({
        title: t('settingsModel.flow.confirmReuseTitle'),
        message: t('settingsModel.flow.confirmReuse', { from, to }),
        confirmLabel: t('settingsModel.flow.confirmProceed'),
        cancelLabel: t('coachConversation.cancel'),
        tone: 'primary',
        onConfirm: () => {
          setConfirmDialog(null)
          resolve(true)
        },
        onCancel: () => {
          setConfirmDialog(null)
          resolve(false)
        },
      })
    })
  }, [t])

  const state = useModelSettings({ confirmReuse })
  const { workspace, editing, providers, loading, dirty, action, feedback, patch } = state
  const busy = action !== null

  useEffect(() => {
    setAdvancedOpen(editing.provider_id === 'custom')
    setUrlTouched(false)
    setKeyVisible(false)
    setModelDropdownOpen(false)
  }, [editing.provider_id])

  useEffect(() => {
    if (!modelDropdownOpen) return
    const handleOutsideClick = (event: MouseEvent) => {
      if (comboboxRef.current && !comboboxRef.current.contains(event.target as Node)) {
        setModelDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [modelDropdownOpen])

  const providerLabel = useCallback((item: Pick<ModelProviderPreset, 'id' | 'display_name'>) => {
    const key = PRESET_LABEL_KEYS[item.id]
    return key ? t(key) : item.display_name
  }, [t])

  const filteredModels = useMemo(() => {
    const all = state.models ?? []
    if (!filteringModels) return all
    const query = editing.model.trim().toLowerCase()
    if (!query || all.some(item => item.toLowerCase() === query)) return all
    return all.filter(item => item.toLowerCase().includes(query))
  }, [state.models, editing.model, filteringModels])

  if (loading && !workspace) {
    return <div className="settings-loading">{t('settingsModel.loading')}…</div>
  }
  if (!workspace) {
    return (
      <div className="page-stack settings-page">
        <Link to={returnTo ?? '/settings'} className="secondary-button">{t('settingsModel.back')}</Link>
        <h1>{t('settingsModel.title')}</h1>
        <p role="alert">{feedback?.message ?? t('settingsModel.loadError')}</p>
        <button className="secondary-button" type="button" onClick={() => void state.refresh()}>
          {t('common.tryAgain')}
        </button>
      </div>
    )
  }

  const preset = providers.find(item => item.id === editing.provider_id) ?? null
  const active = workspace.active
  const draft = workspace.draft
  const source = editing.credential_mode === 'reuse_draft' ? draft : active
  const canReuseActive = Boolean(active?.api_key_configured && (active.provider_id ?? active.provider) === editing.provider_id)
  const canReuseDraft = Boolean(draft?.api_key_configured && (draft.provider_id ?? draft.provider) === editing.provider_id)

  const urlErrorKey = validateEndpointUrl(editing.base_url)
  const showUrlError = Boolean(urlErrorKey && (urlTouched || editing.base_url.trim().length > 0))
  const credentialReady = editing.credential_mode === 'new'
    ? Boolean(editing.api_key?.trim())
    : Boolean(source?.api_key_configured)
  const connectionReady = Boolean(editing.provider_id && editing.base_url.trim() && !urlErrorKey && credentialReady)
  const testReady = connectionReady && Boolean(editing.model.trim())

  const endpointPath = editing.base_url.trim()
    ? `${editing.base_url.trim().replace(/\/+$/, '')}${editing.protocol === 'responses' ? '/responses' : '/chat/completions'}`
    : ''

  const diagnosticCode = state.probeResult?.generation.status === 'passed' && state.probeResult?.structured.status === 'failed'
    ? 'STRUCTURED_FAILED'
    : (state.probeResult?.generation.error_code
      ?? state.probeResult?.structured.error_code
      ?? state.lastErrorCode
      ?? null)
  const diagnosticKey = diagnosticCode ? DIAGNOSTIC_KEYS[diagnosticCode] : null

  const activeProviderName = active
    ? (() => {
        const id = active.provider_id ?? active.provider
        const found = providers.find(item => item.id === id)
        return found ? providerLabel(found) : (PRESET_LABEL_KEYS[id] ? t(PRESET_LABEL_KEYS[id]) : id)
      })()
    : null

  function requestLoad(slot: 'active' | 'draft') {
    if (!dirty) {
      state.load(slot)
      return
    }
    setConfirmDialog({
      title: t('settingsModel.flow.confirmDiscardTitle'),
      message: t('settingsModel.flow.confirmDiscardBody'),
      confirmLabel: t('settingsModel.flow.confirmLeave'),
      cancelLabel: t('settingsModel.flow.confirmStay'),
      tone: 'danger',
      onConfirm: () => {
        setConfirmDialog(null)
        state.load(slot)
      },
    })
  }

  function requestDisable() {
    setConfirmDialog({
      title: t('settingsModel.flow.confirmDisableTitle'),
      message: t('settingsModel.flow.confirmDisableBody'),
      confirmLabel: t('settingsModel.flow.disable'),
      cancelLabel: t('coachConversation.cancel'),
      tone: 'danger',
      onConfirm: () => {
        setConfirmDialog(null)
        void state.disable()
      },
    })
  }

  function requestClearKey(slot: 'active' | 'draft') {
    setConfirmDialog({
      title: t('settingsModel.flow.confirmClearTitle'),
      message: t('settingsModel.flow.confirmClearBody'),
      confirmLabel: t(slot === 'active' ? 'settingsModel.flow.clearActive' : 'settingsModel.flow.clearDraft'),
      cancelLabel: t('coachConversation.cancel'),
      tone: 'danger',
      onConfirm: () => {
        setConfirmDialog(null)
        void state.clearApiKey(slot)
      },
    })
  }

  async function handleListModels() {
    const loaded = await state.listModels()
    if (loaded) {
      setFilteringModels(false)
      setModelDropdownOpen(true)
      modelInputRef.current?.focus()
    }
  }

  function handleSelectProvider(id: string) {
    if (typeof state.selectProvider === 'function') {
      state.selectProvider(id)
    } else {
      const next = providers.find(item => item.id === id)
      patch({
        provider_id: id,
        base_url: next?.default_base_url ?? '',
        model: '',
        protocol: next?.recommended_protocol ?? 'chat_completions',
      })
    }
  }

  const returnLabel = returnTo === '/coach'
    ? t('settingsModel.flow.returnToCoach')
    : returnTo
      ? t('settingsModel.flow.returnToCaller')
      : t('settingsModel.flow.goToCoach')

  return (
    <div className="page-stack settings-page model-settings-page">
      <UnsavedModelChanges dirty={dirty} />
      <ConfirmModal
        open={confirmDialog !== null}
        title={confirmDialog?.title ?? ''}
        message={confirmDialog?.message ?? ''}
        confirmLabel={confirmDialog?.confirmLabel ?? ''}
        cancelLabel={confirmDialog?.cancelLabel ?? t('coachConversation.cancel')}
        tone={confirmDialog?.tone}
        busy={busy}
        onConfirm={() => confirmDialog?.onConfirm()}
        onCancel={() => {
          const onCancel = confirmDialog?.onCancel
          setConfirmDialog(null)
          onCancel?.()
        }}
      />

      <header className="settings-task-header">
        <Link className="icon-button" to={returnTo ?? '/settings'} aria-label={t('settingsModel.back')}>
          <ArrowLeft size={20} />
        </Link>
        <div className="page-header">
          <span>{t('settings.title')}</span>
          <h1>{t('settingsModel.title')}</h1>
        </div>
        {dirty ? (
          <span className="model-state untested">
            <span />
            {t('settingsModel.flow.unsaved')}
          </span>
        ) : null}
      </header>

      <section className="model-status-strip" aria-label={t('settingsModel.flow.current')}>
        <div className="model-status-strip-main">
          {active ? (
            <>
              <span className={`model-state ${active.enabled ? 'success' : 'disabled'}`}>
                <span />
                {t(active.enabled ? 'settingsModel.flow.active' : 'settingsModel.states.disabled')}
              </span>
              <strong>{activeProviderName} · {active.model}</strong>
              {active.enabled && (active.generation_status !== 'passed' || active.structured_status !== 'passed') ? (
                <small className="muted-copy">{t('settingsModel.flow.legacy')}</small>
              ) : null}
            </>
          ) : (
            <>
              <span className="model-state disabled">
                <span />
                {t('settingsModel.flow.noActiveShort')}
              </span>
              <span className="muted-copy">{t('settingsModel.flow.noActive')}</span>
            </>
          )}
        </div>
        {active ? (
          <div className="model-status-strip-actions">
            {active.enabled ? (
              <button type="button" className="secondary-button compact-btn" disabled={busy} onClick={requestDisable}>
                {t('settingsModel.flow.disable')}
              </button>
            ) : (
              <button type="button" className="secondary-button compact-btn" disabled={busy} onClick={() => requestLoad('active')}>
                {t('settingsModel.flow.loadActive')}
              </button>
            )}
            {active.api_key_configured ? (
              <button type="button" className="danger-button compact-btn" disabled={busy} onClick={() => requestClearKey('active')}>
                {t('settingsModel.flow.clearActive')}
              </button>
            ) : null}
          </div>
        ) : null}
      </section>

      {draft ? (
        <div className="model-draft-banner" role="status">
          <span>{t('settingsModel.flow.draftAvailable', { model: draft.model })}</span>
          <div className="model-status-strip-actions">
            <button type="button" className="secondary-button compact-btn" disabled={busy} onClick={() => requestLoad('draft')}>
              {t('settingsModel.flow.continueDraft')}
            </button>
            {draft.api_key_configured ? (
              <button type="button" className="danger-button compact-btn" disabled={busy} onClick={() => requestClearKey('draft')}>
                {t('settingsModel.flow.clearDraft')}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      {state.conflictDetected ? (
        <div className="model-conflict-banner" role="alert">
          <AlertTriangle size={16} />
          <span>{t('settingsModel.flow.conflictNotice')}</span>
          <button type="button" className="secondary-button compact-btn" disabled={busy} onClick={() => void state.refresh()}>
            <RefreshCw size={14} />
            {t('settingsModel.flow.refreshConflict')}
          </button>
        </div>
      ) : null}

      <div className="model-workbench-grid">
        <aside className="model-provider-rail" aria-label={t('settingsModel.flow.providerList')}>
          <h2>{t('settingsModel.flow.providerList')}</h2>
          <div className="model-provider-list" role="radiogroup" aria-label={t('settingsModel.providerLabel')}>
            {providers.map((item) => {
              const selected = editing.provider_id === item.id
              const isActiveProvider = Boolean(active?.enabled && (active.provider_id ?? active.provider) === item.id)
              const isDraftProvider = Boolean(draft && (draft.provider_id ?? draft.provider) === item.id)
              return (
                <button
                  key={item.id}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  className={`model-provider-card ${selected ? 'selected' : ''}`}
                  disabled={busy}
                  onClick={() => handleSelectProvider(item.id)}
                >
                  <span className="model-provider-name">{providerLabel(item)}</span>
                  <span className="model-provider-badges">
                    {isActiveProvider ? <span className="provider-pill active">{t('settingsModel.flow.activeBadge')}</span> : null}
                    {isDraftProvider && !isActiveProvider ? <span className="provider-pill draft">{t('settingsModel.flow.draftBadge')}</span> : null}
                  </span>
                </button>
              )
            })}
          </div>
        </aside>

        <form className="panel-card model-config-card" onSubmit={event => event.preventDefault()}>
          {preset ? (
            <>
              <header className="model-config-header">
                <h2>{t('settingsModel.flow.configTitle', { provider: providerLabel(preset) })}</h2>
                {preset.default_base_url ? (
                  <span className="model-endpoint-chip">{preset.default_base_url}</span>
                ) : null}
              </header>

              {/* API Key */}
              <div className="model-field-block">
                <div className="model-field-label-row">
                  <label htmlFor="model-api-key">{t('settingsModel.apiKey')}</label>
                  {editing.credential_mode !== 'new' ? (
                    <button
                      type="button"
                      className="text-link-button"
                      disabled={busy}
                      onClick={() => patch({ credential_mode: 'new', api_key: '' })}
                    >
                      {t('settingsModel.flow.replaceKey')}
                    </button>
                  ) : (canReuseActive || canReuseDraft) ? (
                    <button
                      type="button"
                      className="text-link-button"
                      disabled={busy}
                      onClick={() => patch({
                        credential_mode: canReuseActive ? 'reuse_active' : 'reuse_draft',
                        api_key: '',
                      })}
                    >
                      {t('settingsModel.flow.keepSavedKey')}
                    </button>
                  ) : null}
                </div>

                {editing.credential_mode !== 'new' ? (
                  <div className="saved-credential-pill">
                    <KeyRound size={15} />
                    <span>{t('settingsModel.savedKey', { hint: source?.api_key_hint ?? '' })}</span>
                  </div>
                ) : (
                  <div className="password-field">
                    <input
                      id="model-api-key"
                      type={keyVisible ? 'text' : 'password'}
                      value={editing.api_key ?? ''}
                      autoComplete="new-password"
                      placeholder={t('settingsModel.enterKey')}
                      disabled={busy}
                      onChange={event => patch({ api_key: event.target.value })}
                      onPaste={event => {
                        const pasted = event.clipboardData.getData('text')
                        if (pasted !== pasted.trim()) {
                          event.preventDefault()
                          patch({ api_key: pasted.trim() })
                        }
                      }}
                      onBlur={() => {
                        const current = editing.api_key ?? ''
                        if (current !== current.trim()) patch({ api_key: current.trim() })
                      }}
                    />
                    <button
                      type="button"
                      onClick={() => setKeyVisible(visible => !visible)}
                      aria-label={keyVisible ? t('settingsModel.flow.hideKey') : t('settingsModel.flow.showKey')}
                    >
                      {keyVisible ? <EyeOff size={18} /> : <Eye size={18} />}
                    </button>
                  </div>
                )}
                <small className="field-hint">{t('settingsModel.flow.keyTrimHint')}</small>
              </div>

              {/* Model Selector (Searchable Combobox + Recommended Chips) */}
              <div className="model-field-block" ref={comboboxRef}>
                <label htmlFor="model-name">{t('settingsModel.modelName')}</label>
                <div className="model-combobox-row">
                  <div className="model-combobox-input-wrap">
                    <input
                      ref={modelInputRef}
                      id="model-name"
                      role="combobox"
                      aria-expanded={modelDropdownOpen && state.models.length > 0}
                      aria-controls="model-options-listbox"
                      aria-autocomplete="list"
                      placeholder={t('settingsModel.flow.modelPlaceholder')}
                      value={editing.model}
                      disabled={busy}
                      onFocus={() => { if (state.models.length > 0) setModelDropdownOpen(true) }}
                      onChange={event => {
                        patch({ model: event.target.value })
                        setFilteringModels(true)
                        if (state.models.length > 0) setModelDropdownOpen(true)
                      }}
                      onKeyDown={event => {
                        if (event.key === 'Escape') setModelDropdownOpen(false)
                      }}
                    />
                    {state.models.length > 0 ? (
                      <button
                        type="button"
                        className="combobox-toggle"
                        aria-label={t('settingsModel.flow.toggleModelList')}
                        onClick={() => {
                          setFilteringModels(false)
                          setModelDropdownOpen(open => !open)
                        }}
                      >
                        <ChevronDown size={16} />
                      </button>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={busy || !connectionReady}
                    onClick={() => void handleListModels()}
                  >
                    <RefreshCw size={15} className={action === 'list' ? 'spin-icon' : ''} />
                    {t('settingsModel.getModels')}
                  </button>
                </div>

                {modelDropdownOpen && state.models.length > 0 ? (
                  <div className="model-combobox-popover">
                    {filteredModels.length > 0 ? (
                      <ul id="model-options-listbox" role="listbox" className="model-combobox-list">
                        {filteredModels.map(modelId => (
                          <li key={modelId} role="option" aria-selected={editing.model === modelId}>
                            <button
                              type="button"
                              className={editing.model === modelId ? 'selected' : ''}
                              onClick={() => {
                                patch({ model: modelId })
                                setModelDropdownOpen(false)
                              }}
                            >
                              <span>{modelId}</span>
                              {editing.model === modelId ? <Check size={14} /> : null}
                            </button>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="combobox-empty">{t('settingsModel.flow.noMatchingModels')}</p>
                    )}
                  </div>
                ) : null}

                {preset.recommended_models && preset.recommended_models.length > 0 ? (
                  <div className="model-recommended-row">
                    <span className="recommended-label">{t('settingsModel.flow.recommendedModels')}:</span>
                    <div className="model-recommended-chips">
                      {preset.recommended_models.map((modelId) => (
                        <button
                          key={modelId}
                          type="button"
                          className={`chip-toggle ${editing.model === modelId ? 'selected' : ''}`}
                          disabled={busy}
                          onClick={() => patch({ model: modelId })}
                        >
                          {modelId}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
                <small className="field-hint">{t('settingsModel.flow.listOptional')}</small>
              </div>

              {/* Advanced Settings (URL + Protocol; auto-expanded for Custom) */}
              <details
                className="model-advanced-box"
                open={advancedOpen}
                onToggle={event => setAdvancedOpen((event.currentTarget as HTMLDetailsElement).open)}
              >
                <summary>{t('settingsModel.flow.advancedSection')}</summary>
                <div className="model-advanced-body">
                  <label className="settings-field" htmlFor="model-base-url">
                    <span>{t('settingsModel.baseUrl')}</span>
                    <input
                      id="model-base-url"
                      type="url"
                      value={editing.base_url}
                      disabled={busy}
                      placeholder="https://models.example.com/v1"
                      onChange={event => patch({ base_url: event.target.value })}
                      onBlur={() => setUrlTouched(true)}
                    />
                  </label>
                  {showUrlError && urlErrorKey ? (
                    <p className="inline-warning" role="alert">
                      <AlertTriangle size={14} />
                      {t(`settingsModel.flow.${urlErrorKey}`)}
                    </p>
                  ) : endpointPath ? (
                    <small className="field-hint model-endpoint">
                      {t('settingsModel.flow.endpointPreview', { url: endpointPath })}
                    </small>
                  ) : null}

                  <label className="settings-field" htmlFor="model-protocol">
                    <span>{t('settingsModel.protocol')}</span>
                    <select
                      id="model-protocol"
                      value={editing.protocol}
                      disabled={busy}
                      onChange={event => patch({ protocol: event.target.value as ModelProtocol })}
                    >
                      {preset.protocols.map(protocol => (
                        <option key={protocol} value={protocol}>
                          {t(protocol === 'responses' ? 'settingsModel.responses' : 'settingsModel.chatCompletions')}
                        </option>
                      ))}
                    </select>
                  </label>
                  <small className="field-hint">{t('settingsModel.protocolDescription')}</small>
                </div>
              </details>

              {/* Inline Test Progress & Human-Readable Diagnosis */}
              <div className="model-probe-panel" aria-live="polite">
                {action === 'test' || action === 'test_and_enable' ? (
                  <div className="probe-live-progress">
                    <Sparkles size={15} />
                    <span>
                      {t(state.probePhase === 'activating'
                        ? 'settingsModel.flow.activatingStep'
                        : 'settingsModel.flow.testingSteps')}
                    </span>
                  </div>
                ) : null}

                {state.tokenExpiredNotice ? (
                  <div className="settings-feedback error" role="status">
                    {t('settingsModel.flow.tokenExpiredNotice')}
                  </div>
                ) : null}

                {state.probeResult ? (
                  <div className={`probe-summary-card ${state.probeResult.status === 'success' ? 'passed' : 'failed'}`}>
                    <div className="probe-summary-headline">
                      {state.probeResult.status === 'success' ? <CheckCircle2 size={17} /> : <XCircle size={17} />}
                      <p>
                        {t(state.probeResult.status === 'success'
                          ? 'settingsModel.flow.connectionSuccess'
                          : state.probeResult.generation.status === 'passed'
                            ? 'settingsModel.flow.businessFailed'
                            : 'settingsModel.flow.connectionFailed')}
                      </p>
                    </div>

                    <ul className="probe-step-list">
                      {(['generation', 'structured'] as const).map((stepName) => {
                        const step = state.probeResult?.[stepName]
                        const status = step?.status ?? 'not_run'
                        return (
                          <li key={stepName} data-status={status}>
                            <strong>{t(`settingsModel.flow.${stepName}`)}</strong>
                            <span>{t(`settingsModel.flow.${status}`)}</span>
                            {step?.latency_ms !== undefined ? (
                              <small>{t('settingsModel.flow.latency', { count: step.latency_ms })}</small>
                            ) : null}
                          </li>
                        )
                      })}
                    </ul>

                    {state.probeResult.status !== 'success' && diagnosticKey ? (
                      <p className="probe-diagnostic-advice">{t(diagnosticKey)}</p>
                    ) : null}

                    <details className="probe-tech-details">
                      <summary>{t('settingsModel.flow.checkDetails')}</summary>
                      {(['generation', 'structured'] as const).map(name => (
                        <div key={name} data-status={state.probeResult?.[name].status ?? 'not_run'}>
                          <strong>{t(`settingsModel.flow.${name}`)}</strong>
                          <span>{t(`settingsModel.flow.${state.probeResult?.[name].status ?? 'not_run'}`)}</span>
                          {state.probeResult?.[name].latency_ms !== undefined ? (
                            <small>{t('settingsModel.flow.latency', { count: state.probeResult[name].latency_ms })}</small>
                          ) : null}
                          {state.probeResult?.[name].error_code ? (
                            <code>{state.probeResult[name].error_code}</code>
                          ) : null}
                        </div>
                      ))}
                    </details>
                  </div>
                ) : null}

                {feedback ? (
                  <div className={`settings-feedback ${feedback.kind}`} role="status">
                    <div>
                      <span>{feedback.message}</span>
                      {feedback.kind === 'error' && diagnosticKey && !state.probeResult ? (
                        <p className="probe-diagnostic-advice">{t(diagnosticKey)}</p>
                      ) : null}
                    </div>
                    {state.justActivated ? (
                      <Link className="primary-button compact-btn" to={returnTo ?? '/coach'}>
                        {returnLabel}
                        <ArrowRight size={15} />
                      </Link>
                    ) : null}
                  </div>
                ) : null}
              </div>

              {/* Action Bar */}
              <div className="model-action-footer">
                <p className="field-hint">{t('settingsModel.flow.cost')}</p>
                {!busy && !testReady ? (
                  <p className="model-readiness-hint" role="status">
                    {!credentialReady
                      ? t('settingsModel.flow.needApiKeyHint')
                      : !editing.model.trim()
                        ? t('settingsModel.flow.needModelHint')
                        : t('settingsModel.flow.needUrlHint')}
                  </p>
                ) : null}
                <div className="settings-actions">
                  <button
                    type="button"
                    className="primary-button"
                    disabled={busy || !testReady}
                    onClick={() => void (state.testAndEnable ? state.testAndEnable() : state.save(true))}
                  >
                    <Zap size={16} />
                    {action === 'test_and_enable'
                      ? t('settingsModel.flow.testingAndEnabling')
                      : t('settingsModel.flow.testAndEnable')}
                  </button>
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={busy || !testReady}
                    onClick={() => void state.testConnection()}
                  >
                    <FlaskConical size={15} />
                    {action === 'test' ? t('settingsModel.testing') : t('settingsModel.flow.testOnly')}
                  </button>
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={busy || !testReady}
                    onClick={() => void state.save(false)}
                  >
                    <Save size={15} />
                    {t('settingsModel.flow.saveDraftShort')}
                  </button>
                </div>
              </div>
            </>
          ) : (
            <p className="muted-copy">{t('settingsModel.flow.selectProviderPrompt')}</p>
          )}
        </form>
      </div>
    </div>
  )
}
