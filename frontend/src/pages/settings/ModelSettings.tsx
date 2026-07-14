import { ArrowLeft, CheckCircle2, FlaskConical, KeyRound, RefreshCw, Save, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { useModelSettings } from '../../hooks/useModelSettings'
import type { ModelProtocol, ModelProvider, ModelSettingsUpdate } from '../../types'

const stateLabels = {
  unconfigured: 'Not configured',
  disabled: 'Disabled',
  untested: 'Not tested',
  success: 'Test passed',
  failed: 'Test failed',
}

export function ModelSettings() {
  const {
    settings,
    models,
    loading,
    action,
    feedback,
    refresh,
    save,
    clearApiKey,
    listModels,
    testConnection,
  } = useModelSettings()
  const [provider, setProvider] = useState<ModelProvider>('openai')
  const [protocol, setProtocol] = useState<ModelProtocol>('responses')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('gpt-5.5')
  const [apiKey, setApiKey] = useState('')
  const [enabled, setEnabled] = useState(false)

  useEffect(() => {
    if (!settings) return
    setProvider(settings.provider)
    setProtocol(settings.protocol)
    setBaseUrl(settings.base_url ?? '')
    setModel(settings.model)
    setEnabled(settings.enabled)
  }, [settings])

  const busy = action !== null

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const payload: ModelSettingsUpdate = {
      provider,
      protocol,
      base_url: provider === 'custom' ? baseUrl.trim() || null : null,
      model: model.trim(),
      enabled,
    }
    if (apiKey.trim()) payload.api_key = apiKey.trim()
    const saved = await save(payload)
    if (saved) setApiKey('')
  }

  if (loading && !settings) {
    return <div className="settings-loading">Loading model settings...</div>
  }

  if (!settings) {
    return (
      <div className="page-stack settings-page">
        <header className="page-header"><h1>Model connection</h1></header>
        <div className="settings-loading settings-load-error">
          <p>{feedback?.message ?? 'Model settings could not be loaded.'}</p>
          <button className="secondary-button" type="button" onClick={() => void refresh()}>Try again</button>
        </div>
      </div>
    )
  }

  return (
    <div className="page-stack settings-page model-settings-page">
      <header className="settings-task-header">
        <Link className="icon-button" to="/settings" aria-label="Back to settings"><ArrowLeft size={20} /></Link>
        <div className="page-header">
          <span>Settings</span>
          <h1>Model connection</h1>
        </div>
        <div className={`model-state ${settings.state}`}>
          <span aria-hidden="true" />
          {stateLabels[settings.state]}
        </div>
      </header>

      <form className="settings-form" onSubmit={(event) => void submit(event)}>
        <section className="settings-section">
          <div className="settings-section-heading">
            <h2>Provider</h2>
            <p>Choose the service and API protocol used by Agent actions.</p>
          </div>
          <div className="settings-section-control">
            <div className="settings-segmented" role="group" aria-label="Model provider">
              <button type="button" className={provider === 'openai' ? 'active' : ''} aria-pressed={provider === 'openai'} onClick={() => setProvider('openai')}>OpenAI</button>
              <button type="button" className={provider === 'custom' ? 'active' : ''} aria-pressed={provider === 'custom'} onClick={() => setProvider('custom')}>Custom</button>
            </div>
            {provider === 'custom' ? (
              <label className="settings-field">
                <span>Base URL</span>
                <input type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://models.example.com/v1" required />
              </label>
            ) : null}
          </div>
        </section>

        <section className="settings-section">
          <div className="settings-section-heading">
            <h2>Protocol</h2>
            <p>The protocol is explicit and will not be detected or changed automatically.</p>
          </div>
          <div className="settings-section-control">
            <div className="settings-segmented" role="group" aria-label="API protocol">
              <button type="button" className={protocol === 'responses' ? 'active' : ''} aria-pressed={protocol === 'responses'} onClick={() => setProtocol('responses')}>Responses</button>
              <button type="button" className={protocol === 'chat_completions' ? 'active' : ''} aria-pressed={protocol === 'chat_completions'} onClick={() => setProtocol('chat_completions')}>Chat Completions</button>
            </div>
          </div>
        </section>

        <section className="settings-section">
          <div className="settings-section-heading">
            <h2>Model</h2>
            <p>Enter a model manually or load options from the saved connection.</p>
          </div>
          <div className="settings-section-control settings-model-control">
            <label className="settings-field">
              <span>Model name</span>
              <input list="model-options" value={model} onChange={(event) => setModel(event.target.value)} required />
              <datalist id="model-options">
                {models.map((item) => <option key={item} value={item} />)}
              </datalist>
            </label>
            <button className="secondary-button" type="button" disabled={busy || !settings.api_key_configured} onClick={() => void listModels()}>
              <RefreshCw size={17} className={action === 'list' ? 'spin' : ''} />
              {action === 'list' ? 'Loading...' : 'Get models'}
            </button>
          </div>
        </section>

        <section className="settings-section">
          <div className="settings-section-heading">
            <h2>API key</h2>
            <p>The key is encrypted by the backend and is never returned to this page.</p>
          </div>
          <div className="settings-section-control settings-key-control">
            <label className="settings-field">
              <span>{settings.api_key_configured ? `Saved key ${settings.api_key_hint ?? ''}` : 'New API key'}</span>
              <span className="settings-input-with-icon">
                <KeyRound size={17} aria-hidden="true" />
                <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} autoComplete="new-password" placeholder={settings.api_key_configured ? 'Leave blank to keep saved key' : 'Enter API key'} />
              </span>
            </label>
            {settings.api_key_configured ? (
              <button className="danger-button" type="button" disabled={busy} onClick={() => void clearApiKey()}>
                <Trash2 size={17} />
                {action === 'clear' ? 'Clearing...' : 'Clear key'}
              </button>
            ) : null}
          </div>
        </section>

        <section className="settings-section">
          <div className="settings-section-heading">
            <h2>Availability</h2>
            <p>Untested connections may be enabled. Agent actions use only the saved connection.</p>
          </div>
          <div className="settings-section-control">
            <label className="settings-switch">
              <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
              <span className="settings-switch-track" aria-hidden="true"><span /></span>
              <span><strong>Enable Agent connection</strong><small>{enabled ? 'Available after saving' : 'Agent actions are disabled'}</small></span>
            </label>
          </div>
        </section>

        {feedback ? <div className={`settings-feedback ${feedback.kind}`} role="status">{feedback.kind === 'success' ? <CheckCircle2 size={18} /> : null}{feedback.message}</div> : null}

        <footer className="settings-actions">
          <button className="secondary-button" type="button" disabled={busy || !settings.api_key_configured} onClick={() => void testConnection()}>
            <FlaskConical size={17} />
            {action === 'test' ? 'Testing...' : 'Test saved connection'}
          </button>
          <button className="primary-button" type="submit" disabled={busy}>
            <Save size={17} />
            {action === 'save' ? 'Saving...' : 'Save changes'}
          </button>
        </footer>
      </form>
    </div>
  )
}
