import { ArrowLeft, CheckCircle2, FlaskConical, KeyRound, RefreshCw, Save, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { useModelSettings } from '../../hooks/useModelSettings'
import type { ModelProtocol, ModelProvider, ModelSettingsUpdate } from '../../types'

export function ModelSettings() {
  const { t } = useTranslation()
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
  const stateLabels = {
    unconfigured: t('settingsModel.states.unconfigured'), disabled: t('settingsModel.states.disabled'),
    untested: t('settingsModel.states.untested'), success: t('settingsModel.states.success'), failed: t('settingsModel.states.failed'),
  }

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
    return <div className="settings-loading">{t('settingsModel.loading')}...</div>
  }

  if (!settings) {
    return (
      <div className="page-stack settings-page">
        <header className="page-header"><h1>{t('settingsModel.title')}</h1></header>
        <div className="settings-loading settings-load-error">
          <p>{feedback?.message ?? t('settingsModel.loadError')}</p>
          <button className="secondary-button" type="button" onClick={() => void refresh()}>{t('common.tryAgain')}</button>
        </div>
      </div>
    )
  }

  return (
    <div className="page-stack settings-page model-settings-page">
      <header className="settings-task-header">
        <Link className="icon-button" to="/settings" aria-label={t('settingsModel.back')}><ArrowLeft size={20} /></Link>
        <div className="page-header">
          <span>{t('settings.title')}</span>
          <h1>{t('settingsModel.title')}</h1>
        </div>
        <div className={`model-state ${settings.state}`}>
          <span aria-hidden="true" />
          {stateLabels[settings.state]}
        </div>
      </header>

      <form className="settings-form" onSubmit={(event) => void submit(event)}>
        <section className="settings-section">
          <div className="settings-section-heading">
            <h2>{t('settingsModel.provider')}</h2>
            <p>{t('settingsModel.providerDescription')}</p>
          </div>
          <div className="settings-section-control">
            <div className="settings-segmented" role="group" aria-label={t('settingsModel.providerLabel')}>
              <button type="button" className={provider === 'openai' ? 'active' : ''} aria-pressed={provider === 'openai'} onClick={() => setProvider('openai')}>OpenAI</button>
              <button type="button" className={provider === 'custom' ? 'active' : ''} aria-pressed={provider === 'custom'} onClick={() => setProvider('custom')}>{t('settingsModel.custom')}</button>
            </div>
            {provider === 'custom' ? (
              <label className="settings-field">
                <span>{t('settingsModel.baseUrl')}</span>
                <input type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://models.example.com/v1" required />
              </label>
            ) : null}
          </div>
        </section>

        <section className="settings-section">
          <div className="settings-section-heading">
            <h2>{t('settingsModel.protocol')}</h2>
            <p>{t('settingsModel.protocolDescription')}</p>
          </div>
          <div className="settings-section-control">
            <div className="settings-segmented" role="group" aria-label={t('settingsModel.protocolLabel')}>
              <button type="button" className={protocol === 'responses' ? 'active' : ''} aria-pressed={protocol === 'responses'} onClick={() => setProtocol('responses')}>{t('settingsModel.responses')}</button>
              <button type="button" className={protocol === 'chat_completions' ? 'active' : ''} aria-pressed={protocol === 'chat_completions'} onClick={() => setProtocol('chat_completions')}>{t('settingsModel.chatCompletions')}</button>
            </div>
          </div>
        </section>

        <section className="settings-section">
          <div className="settings-section-heading">
            <h2>{t('settingsModel.model')}</h2>
            <p>{t('settingsModel.modelDescription')}</p>
          </div>
          <div className="settings-section-control settings-model-control">
            <label className="settings-field">
              <span>{t('settingsModel.modelName')}</span>
              <input list="model-options" value={model} onChange={(event) => setModel(event.target.value)} required />
              <datalist id="model-options">
                {models.map((item) => <option key={item} value={item} />)}
              </datalist>
            </label>
            <button className="secondary-button" type="button" disabled={busy || !settings.api_key_configured} onClick={() => void listModels()}>
              <RefreshCw size={17} className={action === 'list' ? 'spin' : ''} />
              {action === 'list' ? `${t('common.loading')}...` : t('settingsModel.getModels')}
            </button>
          </div>
        </section>

        <section className="settings-section">
          <div className="settings-section-heading">
            <h2>{t('settingsModel.apiKey')}</h2>
            <p>{t('settingsModel.apiKeyDescription')}</p>
          </div>
          <div className="settings-section-control settings-key-control">
            <label className="settings-field">
              <span>{settings.api_key_configured ? t('settingsModel.savedKey', { hint: settings.api_key_hint ?? '' }) : t('settingsModel.newKey')}</span>
              <span className="settings-input-with-icon">
                <KeyRound size={17} aria-hidden="true" />
                <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} autoComplete="new-password" placeholder={settings.api_key_configured ? t('settingsModel.keepKey') : t('settingsModel.enterKey')} />
              </span>
            </label>
            {settings.api_key_configured ? (
              <button className="danger-button" type="button" disabled={busy} onClick={() => void clearApiKey()}>
                <Trash2 size={17} />
                {action === 'clear' ? t('settingsModel.clearing') : t('settingsModel.clearKey')}
              </button>
            ) : null}
          </div>
        </section>

        <section className="settings-section">
          <div className="settings-section-heading">
            <h2>{t('settingsModel.availability')}</h2>
            <p>{t('settingsModel.availabilityDescription')}</p>
          </div>
          <div className="settings-section-control">
            <label className="settings-switch">
              <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
              <span className="settings-switch-track" aria-hidden="true"><span /></span>
              <span><strong>{t('settingsModel.enable')}</strong><small>{enabled ? t('settingsModel.availableAfterSaving') : t('settingsModel.disabled')}</small></span>
            </label>
          </div>
        </section>

        {feedback ? <div className={`settings-feedback ${feedback.kind}`} role="status">{feedback.kind === 'success' ? <CheckCircle2 size={18} /> : null}{feedback.message}</div> : null}

        <footer className="settings-actions">
          <button className="secondary-button" type="button" disabled={busy || !settings.api_key_configured} onClick={() => void testConnection()}>
            <FlaskConical size={17} />
            {action === 'test' ? t('settingsModel.testing') : t('settingsModel.test')}
          </button>
          <button className="primary-button" type="submit" disabled={busy}>
            <Save size={17} />
            {action === 'save' ? t('common.saving') : t('settingsModel.saveChanges')}
          </button>
        </footer>
      </form>
    </div>
  )
}
