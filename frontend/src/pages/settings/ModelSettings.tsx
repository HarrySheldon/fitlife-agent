import { ArrowLeft, FlaskConical, RefreshCw, Save } from 'lucide-react'
import { type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { useModelSettings } from '../../hooks/useModelSettings'
import type { ModelConnectionInput, ModelProtocol } from '../../types'
import { UnsavedModelChanges } from './UnsavedModelChanges'

function Step({ number, title, children }: { number: number; title: string; children: ReactNode }) {
  return <section className="settings-section model-setup-step">
    <div className="settings-section-heading"><h2><span className="model-step-number">{number}</span>{title}</h2></div>
    <div className="settings-section-control">{children}</div>
  </section>
}

export function ModelSettings() {
  const { t } = useTranslation()
  const state = useModelSettings()
  const { workspace, editing, providers, loading, dirty, action, feedback, patch } = state
  const busy = action !== null

  if (loading && !workspace) return <div className="settings-loading">{t('settingsModel.loading')}…</div>
  if (!workspace) return <div className="page-stack settings-page">
    <Link to="/settings" className="secondary-button">{t('settingsModel.back')}</Link>
    <h1>{t('settingsModel.title')}</h1><p role="alert">{feedback?.message ?? t('settingsModel.loadError')}</p>
    <button className="secondary-button" onClick={() => void state.refresh()}>{t('common.tryAgain')}</button>
  </div>

  const preset = providers.find(item => item.id === editing.provider_id)
  const source = editing.credential_mode === 'reuse_draft' ? workspace.draft : workspace.active
  const credentialReady = editing.credential_mode === 'new' ? Boolean(editing.api_key?.trim()) : Boolean(source?.api_key_configured)
  const connectionReady = Boolean(editing.provider_id && editing.base_url.trim() && credentialReady)
  const testReady = connectionReady && Boolean(editing.model.trim())
  const active = workspace.active

  function load(slot: 'active' | 'draft') {
    if (!dirty || window.confirm(t('settingsModel.flow.discard'))) state.load(slot)
  }
  function confirmAction(operation: () => Promise<void>) {
    if (window.confirm(t('settingsModel.flow.confirmChange'))) void operation()
  }

  return <div className="page-stack settings-page model-settings-page">
    <UnsavedModelChanges dirty={dirty} />
    <header className="settings-task-header">
      <Link className="icon-button" to="/settings" aria-label={t('settingsModel.back')}><ArrowLeft size={20} /></Link>
      <div className="page-header"><span>{t('settings.title')}</span><h1>{t('settingsModel.title')}</h1></div>
      <span className="model-state">{t(dirty ? 'settingsModel.flow.unsaved' : 'settingsModel.flow.editing')}</span>
    </header>

    <section className="model-active-summary" aria-label={t('settingsModel.flow.current')}>
      <h2>{t('settingsModel.flow.current')}</h2>
      {active ? <>
        <strong>{active.provider_id ?? active.provider} · {active.model}</strong>
        <p className="model-endpoint">{active.base_url ?? providers.find(item => item.id === (active.provider_id ?? active.provider))?.default_base_url ?? t('settingsModel.flow.unspecifiedAddress')}</p>
        <span className={`model-state ${active.enabled ? 'success' : 'disabled'}`}><span />{t(active.enabled ? 'settingsModel.flow.active' : 'settingsModel.states.disabled')}</span>
        {active.enabled && (active.generation_status !== 'passed' || active.structured_status !== 'passed') ? <p>{t('settingsModel.flow.legacy')}</p> : null}
        <div className="settings-actions">
          <button type="button" className="secondary-button" disabled={busy} onClick={() => load('active')}>{t('settingsModel.flow.loadActive')}</button>
          {active.enabled ? <button type="button" className="secondary-button" disabled={busy} onClick={() => confirmAction(state.disable)}>{t('settingsModel.flow.disable')}</button> : null}
          {active.api_key_configured ? <button type="button" className="danger-button" disabled={busy} onClick={() => confirmAction(() => state.clearApiKey('active'))}>{t('settingsModel.flow.clearActive')}</button> : null}
        </div>
      </> : <p>{t('settingsModel.flow.noActive')}</p>}
      {workspace.draft ? <div className="settings-actions">
        <span>{t('settingsModel.flow.draftAvailable', { model: workspace.draft.model })}</span>
        <button type="button" className="secondary-button" disabled={busy} onClick={() => load('draft')}>{t('settingsModel.flow.loadDraft')}</button>
        {workspace.draft.api_key_configured ? <button type="button" className="danger-button" disabled={busy} onClick={() => confirmAction(() => state.clearApiKey('draft'))}>{t('settingsModel.flow.clearDraft')}</button> : null}
      </div> : null}
    </section>

    <form className="settings-form" onSubmit={event => event.preventDefault()}>
      <Step number={1} title={t('settingsModel.flow.chooseProvider')}>
        <label className="settings-field" htmlFor="model-provider"><span>{t('settingsModel.providerLabel')}</span>
          <select id="model-provider" value={editing.provider_id} disabled={busy} onChange={event => {
            const next = providers.find(item => item.id === event.target.value)
            patch({ provider_id: event.target.value, base_url: next?.default_base_url ?? '', model: '', protocol: next?.recommended_protocol ?? 'chat_completions' })
          }}>
            <option value="">{t('settingsModel.flow.chooseProvider')}</option>
            {providers.map(item => <option key={item.id} value={item.id}>{item.id === 'custom' ? t('settingsModel.flow.custom') : item.display_name}</option>)}
          </select>
        </label>
      </Step>

      <Step number={2} title={t('settingsModel.flow.addressAndKey')}>
        <label className="settings-field" htmlFor="model-base-url"><span>{t('settingsModel.baseUrl')}</span>
          <input id="model-base-url" type="url" value={editing.base_url} disabled={busy || !preset} placeholder="https://models.example.com/v1" onChange={event => patch({ base_url: event.target.value })} />
        </label>
        <label className="settings-field" htmlFor="model-credential-mode"><span>{t('settingsModel.flow.credentialSource')}</span>
          <select id="model-credential-mode" value={editing.credential_mode} disabled={busy || !preset} onChange={event => patch({ credential_mode: event.target.value as ModelConnectionInput['credential_mode'], api_key: '' })}>
            <option value="new">{t('settingsModel.newKey')}</option>
            {active?.api_key_configured ? <option value="reuse_active">{t('settingsModel.flow.reuseActive')}</option> : null}
            {workspace.draft?.api_key_configured ? <option value="reuse_draft">{t('settingsModel.flow.reuseDraft')}</option> : null}
          </select>
        </label>
        {editing.credential_mode === 'new' ? <label className="settings-field" htmlFor="model-api-key"><span>{t('settingsModel.apiKey')}</span>
          <input id="model-api-key" type="password" value={editing.api_key ?? ''} autoComplete="new-password" disabled={busy || !preset} onChange={event => patch({ api_key: event.target.value })} />
        </label> : <p>{t('settingsModel.savedKey', { hint: source?.api_key_hint ?? '' })}</p>}
        <p>{t('settingsModel.apiKeyDescription')}</p>
        <details><summary>{t('settingsModel.flow.advanced')}</summary>
          <label className="settings-field" htmlFor="model-protocol"><span>{t('settingsModel.protocol')}</span>
            <select id="model-protocol" value={editing.protocol} disabled={busy || !preset} onChange={event => patch({ protocol: event.target.value as ModelProtocol })}>
              {(preset?.protocols ?? ['chat_completions', 'responses']).map(protocol => <option key={protocol} value={protocol}>{t(protocol === 'responses' ? 'settingsModel.responses' : 'settingsModel.chatCompletions')}</option>)}
            </select>
          </label><p>{t('settingsModel.protocolDescription')}</p>
        </details>
      </Step>

      <Step number={3} title={t('settingsModel.flow.chooseModel')}>
        <label className="settings-field" htmlFor="model-name"><span>{t('settingsModel.modelName')}</span>
          <input id="model-name" list="model-options" value={editing.model} disabled={busy || !preset} onChange={event => patch({ model: event.target.value })} />
          <datalist id="model-options">{state.models.map(model => <option key={model} value={model} />)}</datalist>
        </label>
        <button type="button" className="secondary-button" disabled={busy || !connectionReady} onClick={() => void state.listModels()}><RefreshCw size={16} />{t('settingsModel.getModels')}</button>
        <p>{t('settingsModel.flow.listOptional')}</p>
      </Step>

      <Step number={4} title={t('settingsModel.flow.testCurrent')}>
        <p>{t('settingsModel.flow.cost')}</p>
        <p className="model-endpoint">{t('settingsModel.flow.destination', { url: editing.base_url || '—', model: editing.model || '—' })}</p>
        <button type="button" className="secondary-button" disabled={busy || !testReady} onClick={() => void state.testConnection()}><FlaskConical size={16} />{t(action === 'test' ? 'settingsModel.testing' : 'settingsModel.flow.testCurrent')}</button>
        <div className="model-probe-results" aria-live="polite">
          <p>{t(state.probeResult ? state.probeResult.status === 'success'
            ? 'settingsModel.flow.connectionSuccess' : state.probeResult.generation.status === 'passed'
              ? 'settingsModel.flow.businessFailed' : 'settingsModel.flow.connectionFailed'
            : 'settingsModel.flow.checkHelp')}</p>
        </div>
        {state.probeResult ? <details>
          <summary>{t('settingsModel.flow.checkDetails')}</summary>
          {(['generation', 'structured'] as const).map(name => <div key={name} data-status={state.probeResult?.[name].status ?? 'not_run'}>
            <strong>{t(`settingsModel.flow.${name}`)}</strong>
            <span>{t(`settingsModel.flow.${state.probeResult?.[name].status ?? 'not_run'}`)}</span>
            {state.probeResult?.[name].latency_ms !== undefined ? <small>{t('settingsModel.flow.latency', { count: state.probeResult[name].latency_ms })}</small> : null}
            {state.probeResult?.[name].error_code ? <small>{state.probeResult[name].error_code}</small> : null}
          </div>)}
        </details> : null}
      </Step>

      <Step number={5} title={t('settingsModel.flow.saveAndEnable')}>
        <p>{t('settingsModel.flow.saveHelp')}</p>
        <div className="settings-actions">
          <button type="button" className="secondary-button" disabled={busy || !testReady} onClick={() => void state.save(false)}>{t('settingsModel.flow.saveDraft')}</button>
          <button type="button" className="primary-button" disabled={busy || !state.verificationToken} onClick={() => void state.save(true)}><Save size={16} />{t('settingsModel.flow.saveAndEnable')}</button>
        </div>
      </Step>
    </form>
    {feedback ? <div className={`settings-feedback ${feedback.kind}`} role="status">{feedback.message}</div> : null}
    <button className="secondary-button" type="button" disabled={busy} onClick={() => void state.refresh()}>{t('settingsModel.flow.refresh')}</button>
  </div>
}
