import { ArrowRight, Bot, CalendarDays, Dumbbell, Eye, EyeOff, Flame, Sparkles, Utensils } from 'lucide-react'
import type { FormEvent } from 'react'
import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '../hooks/useAuth'

export function Auth() {
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
          throw new Error('Username, email, or phone is required')
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

  return (
    <main className="auth-shell">
      <section className="auth-hero">
        <div className="auth-hero-top">
          <div className="brand-mark large">FL</div>
          <div className="auth-brand-copy">
            <strong>FitLife Agent</strong>
            <span>AI fitness logbook</span>
          </div>
        </div>

        <div className="auth-hero-copy">
          <span>Training data becomes action</span>
          <h1>Plan, record, and review every fitness day.</h1>
        </div>

        <div className="auth-preview-grid" aria-label="FitLife Agent preview">
          <article className="auth-preview-card auth-status-card">
            <div className="auth-card-heading">
              <Flame size={18} />
              <span>Today</span>
            </div>
            <div className="auth-metric-row">
              <div>
                <strong>1,820</strong>
                <span>kcal</span>
              </div>
              <div>
                <strong>2</strong>
                <span>sessions</span>
              </div>
              <div>
                <strong>96g</strong>
                <span>protein</span>
              </div>
            </div>
          </article>

          <article className="auth-preview-card auth-calendar-card">
            <div className="auth-card-heading">
              <CalendarDays size={18} />
              <span>Week log</span>
            </div>
            <div className="auth-mini-calendar">
              {weekPreview.map((day) => (
                <div className={day.hasData ? 'filled' : ''} key={day.label}>
                  <span>{day.label}</span>
                  <strong>{day.value}</strong>
                </div>
              ))}
            </div>
          </article>

          <article className="auth-preview-card auth-agent-card">
            <div className="auth-card-heading">
              <Bot size={18} />
              <span>Agent entry</span>
            </div>
            <div className="auth-agent-message">
              <Sparkles size={16} />
              <p>Lunch beef rice 650 kcal, evening run 30 min</p>
            </div>
            <div className="auth-agent-result">
              <span><Utensils size={15} /> Meal saved</span>
              <span><Dumbbell size={15} /> Workout saved</span>
            </div>
          </article>
        </div>
      </section>
      <section className="auth-panel">
        <div className="auth-panel-header">
          <span>Account access</span>
          <h2>{mode === 'login' ? 'Log in to FitLife Agent' : 'Create your fitness workspace'}</h2>
        </div>
        <div className="auth-mode">
          <button className={mode === 'login' ? 'active' : ''} type="button" onClick={() => switchMode('login')}>
            Login
          </button>
          <button className={mode === 'register' ? 'active' : ''} type="button" onClick={() => switchMode('register')}>
            Register
          </button>
        </div>
        <form className="auth-form" onSubmit={(event) => void submit(event)}>
          {mode === 'register' ? (
            <>
              <label>
                Display name
                <input
                  required
                  autoComplete="name"
                  name="displayName"
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                />
              </label>
              <div className="auth-identifier-picker" role="group" aria-label="Registration identifier type">
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
              Username / email / phone
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
            Password
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
                aria-label={passwordVisible ? 'Hide password' : 'Show password'}
              >
                {passwordVisible ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </label>
          {error ? <div className="inline-error">{error}</div> : null}
          <button className="primary-button auth-submit" type="submit" disabled={submitting}>
            <Dumbbell size={18} />
            <span>{submitting ? 'Submitting...' : mode === 'login' ? 'Login' : 'Create account'}</span>
            <ArrowRight size={18} />
          </button>
        </form>
      </section>
    </main>
  )
}

const identifierTypeLabels = {
  username: 'Username',
  email: 'Email',
  phone: 'Phone',
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
  { label: 'Mon', value: '1.8k', hasData: true },
  { label: 'Tue', value: '2.1k', hasData: true },
  { label: 'Wed', value: '-', hasData: false },
  { label: 'Thu', value: '1.9k', hasData: true },
  { label: 'Fri', value: '2.0k', hasData: true },
  { label: 'Sat', value: '-', hasData: false },
  { label: 'Sun', value: '1.7k', hasData: true },
]
