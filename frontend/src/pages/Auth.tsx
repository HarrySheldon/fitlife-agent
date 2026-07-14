import { ArrowRight, Bot, CalendarDays, Dumbbell, Eye, EyeOff, Flame, Sparkles, Utensils } from 'lucide-react'
import type { FormEvent } from 'react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '../hooks/useAuth'

export function Auth() {
  const { t } = useTranslation()
  const { user, login, register } = useAuth()
  const [mode, setMode] = useState<'login' | 'register'>('register')
  const [registerIdentifierType, setRegisterIdentifierType] = useState<'username' | 'email' | 'phone'>('email')
  const [identifier, setIdentifier] = useState('')
  const [registerIdentifier, setRegisterIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [passwordVisible, setPasswordVisible] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/'

  if (user) {
    return <Navigate to={from} replace />
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      if (mode === 'register') {
        if (!registerIdentifier.trim()) {
          throw new Error(t('auth.identifierRequired'))
        }
        await register({
          username: registerIdentifierType === 'username' ? registerIdentifier.trim() : undefined,
          email: registerIdentifierType === 'email' ? registerIdentifier.trim() : undefined,
          phone: registerIdentifierType === 'phone' ? registerIdentifier.trim() : undefined,
          password,
          display_name: displayName,
        })
      } else {
        await login({ identifier: identifier.trim(), password })
      }
      navigate(from, { replace: true })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  function switchMode(nextMode: 'login' | 'register') {
    setMode(nextMode)
    setError(null)
    setPassword('')
  }

  const identifierTypeLabels = {
    username: t('auth.username'),
    email: t('auth.email'),
    phone: t('auth.phone'),
  }

  return (
    <main className="auth-shell">
      <section className="auth-hero">
        <div className="auth-hero-top">
          <div className="brand-mark large">FL</div>
          <div className="auth-brand-copy">
            <strong>FitLife Agent</strong>
            <span>{t('auth.tagline')}</span>
          </div>
        </div>

        <div className="auth-hero-copy">
          <span>{t('auth.heroEyebrow')}</span>
          <h1>{t('auth.heroTitle')}</h1>
        </div>

        <div className="auth-preview-grid" aria-label={t('auth.previewLabel')}>
          <article className="auth-preview-card auth-status-card">
            <div className="auth-card-heading">
              <Flame size={18} />
              <span>{t('auth.today')}</span>
            </div>
            <div className="auth-metric-row">
              <div>
                <strong>1,820</strong>
                <span>kcal</span>
              </div>
              <div>
                <strong>2</strong>
                <span>{t('auth.sessions')}</span>
              </div>
              <div>
                <strong>96g</strong>
                <span>{t('auth.protein')}</span>
              </div>
            </div>
          </article>

          <article className="auth-preview-card auth-calendar-card">
            <div className="auth-card-heading">
              <CalendarDays size={18} />
              <span>{t('auth.weekLog')}</span>
            </div>
            <div className="auth-mini-calendar">
              {weekPreview.map((day) => (
                <div className={day.hasData ? 'filled' : ''} key={day.key}>
                  <span>{t(`auth.weekdays.${day.key}`)}</span>
                  <strong>{day.value}</strong>
                </div>
              ))}
            </div>
          </article>

          <article className="auth-preview-card auth-agent-card">
            <div className="auth-card-heading">
              <Bot size={18} />
              <span>{t('auth.agentEntry')}</span>
            </div>
            <div className="auth-agent-message">
              <Sparkles size={16} />
              <p>{t('auth.exampleEntry')}</p>
            </div>
            <div className="auth-agent-result">
              <span><Utensils size={15} /> {t('auth.mealSaved')}</span>
              <span><Dumbbell size={15} /> {t('auth.workoutSaved')}</span>
            </div>
          </article>
        </div>
      </section>
      <section className="auth-panel">
        <div className="auth-panel-header">
          <span>{t('auth.access')}</span>
          <h2>{mode === 'login' ? t('auth.loginTitle') : t('auth.registerTitle')}</h2>
        </div>
        <div className="auth-mode">
          <button className={mode === 'login' ? 'active' : ''} type="button" onClick={() => switchMode('login')}>
            {t('auth.login')}
          </button>
          <button className={mode === 'register' ? 'active' : ''} type="button" onClick={() => switchMode('register')}>
            {t('auth.register')}
          </button>
        </div>
        <form className="auth-form" onSubmit={(event) => void submit(event)}>
          {mode === 'register' ? (
            <>
              <label>
                {t('auth.displayName')}
                <input
                  required
                  autoComplete="name"
                  name="displayName"
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                />
              </label>
              <div className="auth-identifier-picker" role="group" aria-label={t('auth.identifierType')}>
                {(['email', 'phone', 'username'] as const).map((type) => (
                  <button
                    key={type}
                    className={registerIdentifierType === type ? 'active' : ''}
                    type="button"
                    onClick={() => {
                      setRegisterIdentifierType(type)
                      setRegisterIdentifier('')
                    }}
                  >
                    {identifierTypeLabels[type]}
                  </button>
                ))}
              </div>
              <label>
                {identifierTypeLabels[registerIdentifierType]}
                <input
                  required
                  autoComplete={identifierAutocomplete[registerIdentifierType]}
                  name={registerIdentifierType}
                  type={identifierInputTypes[registerIdentifierType]}
                  value={registerIdentifier}
                  onChange={(event) => setRegisterIdentifier(event.target.value)}
                />
              </label>
            </>
          ) : (
            <label>
              {t('auth.identifier')}
              <input
                required
                autoComplete="username"
                name="identifier"
                value={identifier}
                onChange={(event) => setIdentifier(event.target.value)}
              />
            </label>
          )}
          <label>
            {t('auth.password')}
            <div className="password-field">
              <input
                required
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                minLength={8}
                name="password"
                type={passwordVisible ? 'text' : 'password'}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
              <button
                type="button"
                onClick={() => setPasswordVisible((visible) => !visible)}
                aria-label={passwordVisible ? t('auth.hidePassword') : t('auth.showPassword')}
              >
                {passwordVisible ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </label>
          {error ? <div className="inline-error">{error}</div> : null}
          <button className="primary-button auth-submit" type="submit" disabled={submitting}>
            <Dumbbell size={18} />
            <span>{submitting ? t('common.submitting') : mode === 'login' ? t('auth.login') : t('auth.createAccount')}</span>
            <ArrowRight size={18} />
          </button>
        </form>
      </section>
    </main>
  )
}

const identifierAutocomplete = {
  username: 'username',
  email: 'email',
  phone: 'tel',
}

const identifierInputTypes = {
  username: 'text',
  email: 'email',
  phone: 'tel',
}

const weekPreview = [
  { key: 'mon', value: '1.8k', hasData: true },
  { key: 'tue', value: '2.1k', hasData: true },
  { key: 'wed', value: '-', hasData: false },
  { key: 'thu', value: '1.9k', hasData: true },
  { key: 'fri', value: '2.0k', hasData: true },
  { key: 'sat', value: '-', hasData: false },
  { key: 'sun', value: '1.7k', hasData: true },
]
