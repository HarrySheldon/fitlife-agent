import { ArrowRight, Check, Circle, Dumbbell, Eye, EyeOff, Globe, Lock, XCircle } from 'lucide-react'
import type { FormEvent } from 'react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useLocation } from 'react-router-dom'

import { useAuth } from '../hooks/useAuth'
import { api, languageStorage } from '../services/api'
import type { AppLanguage } from '../types'

export function Auth() {
  const { t, i18n } = useTranslation()
  const { user, login, register } = useAuth()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [isFirstRun, setIsFirstRun] = useState(false)
  const [identifier, setIdentifier] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordVisible, setPasswordVisible] = useState(false)
  const [confirmVisible, setConfirmVisible] = useState(false)
  const [confirmTouched, setConfirmTouched] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [postAuthDestination, setPostAuthDestination] = useState<string | null>(null)
  const userTouchedMode = useRef(false)
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/'

  useEffect(() => {
    if (typeof api.authStatus !== 'function') return
    let mounted = true
    void api.authStatus()
      .then((status) => {
        if (!mounted) return
        if (status && status.has_users === false) {
          setIsFirstRun(true)
          if (!userTouchedMode.current) {
            setMode('register')
          }
        } else {
          setIsFirstRun(false)
        }
      })
      .catch(() => undefined)
    return () => { mounted = false }
  }, [])

  if (user) {
    return <Navigate to={postAuthDestination ?? from} replace />
  }

  const trimmedIdentifier = identifier.trim()
  const usernameOk = trimmedIdentifier.length >= 3
  const passwordLengthOk = password.length >= 8
  const passwordsMatch = confirmPassword.length > 0 && password === confirmPassword
  const showMismatch = (confirmTouched || confirmPassword.length >= password.length)
    && confirmPassword.length > 0
    && password !== confirmPassword

  const activeLanguage: AppLanguage = i18n.language === 'zh-CN' ? 'zh-CN' : 'en-US'

  function switchLanguage(next: AppLanguage) {
    languageStorage.set(next)
    void i18n.changeLanguage(next)
  }

  function switchMode(nextMode: 'login' | 'register') {
    userTouchedMode.current = true
    setMode(nextMode)
    setError(null)
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)

    if (mode === 'register') {
      if (!trimmedIdentifier) {
        setError(t('auth.identifierRequired'))
        return
      }
      if (!usernameOk) {
        setError(t('auth.ruleUsernameMin'))
        return
      }
      if (!passwordLengthOk) {
        setError(t('auth.ruleMinChars'))
        return
      }
      if (password !== confirmPassword) {
        setConfirmTouched(true)
        setError(t('auth.rulePasswordMismatch'))
        return
      }
    } else {
      if (!trimmedIdentifier) {
        setError(t('auth.identifierRequired'))
        return
      }
      if (!passwordLengthOk) {
        setError(t('auth.ruleMinChars'))
        return
      }
    }

    setSubmitting(true)
    try {
      if (mode === 'register') {
        setPostAuthDestination('/onboarding')
        await register({
          username: trimmedIdentifier,
          password,
          display_name: displayName.trim() || trimmedIdentifier,
        })
      } else {
        setPostAuthDestination(from)
        await login({ identifier: trimmedIdentifier, password })
      }
    } catch (err) {
      setPostAuthDestination(null)
      setError((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const heading = mode === 'login'
    ? t('auth.loginTitle')
    : isFirstRun
      ? t('auth.initTitle')
      : t('auth.registerTitle')

  const submitLabel = submitting
    ? t('common.submitting')
    : mode === 'login'
      ? t('auth.login')
      : isFirstRun
        ? t('auth.createAndStart')
        : t('auth.createAccount')

  return (
    <main className="auth-shell-centered">
      <header className="auth-topbar">
        <div className="auth-brand-inline">
          <div className="brand-mark">FL</div>
          <div className="auth-brand-copy">
            <strong>FitLife Agent</strong>
            <span>{t('auth.tagline')}</span>
          </div>
        </div>
        <div className="auth-lang-switch" role="group" aria-label={t('auth.languageSwitch')}>
          <Globe size={15} />
          <button
            type="button"
            className={activeLanguage === 'zh-CN' ? 'active' : ''}
            aria-pressed={activeLanguage === 'zh-CN'}
            onClick={() => switchLanguage('zh-CN')}
          >
            中文
          </button>
          <button
            type="button"
            className={activeLanguage === 'en-US' ? 'active' : ''}
            aria-pressed={activeLanguage === 'en-US'}
            onClick={() => switchLanguage('en-US')}
          >
            English
          </button>
        </div>
      </header>

      <div className="auth-center-stage">
        <section className="auth-card">
          <div className="auth-panel-header">
            <span>{t('auth.access')}</span>
            <h2>{heading}</h2>
            <p className="auth-local-subcopy">{t('auth.localHint')}</p>
          </div>

          <div className="auth-mode" role="tablist" aria-label={t('auth.access')}>
            <button
              role="tab"
              aria-selected={mode === 'login'}
              className={mode === 'login' ? 'active' : ''}
              type="button"
              onClick={() => switchMode('login')}
            >
              {t('auth.login')}
            </button>
            <button
              role="tab"
              aria-selected={mode === 'register'}
              className={mode === 'register' ? 'active' : ''}
              type="button"
              onClick={() => switchMode('register')}
            >
              {t('auth.register')}
            </button>
          </div>

          <form className="auth-form" noValidate onSubmit={(event) => void submit(event)}>
            <label>
              <span>{mode === 'register' ? t('auth.username') : t('auth.identifier')}</span>
              <input
                required
                autoComplete="username"
                name={mode === 'register' ? 'username' : 'identifier'}
                placeholder={mode === 'register' ? t('auth.usernamePlaceholder') : t('auth.loginPlaceholder')}
                value={identifier}
                onChange={(event) => setIdentifier(event.target.value)}
              />
              {mode === 'register' ? (
                <small className={`auth-rule-item ${usernameOk ? 'met' : ''}`}>
                  {usernameOk ? <Check size={13} /> : <Circle size={13} />}
                  {t('auth.ruleUsernameMin')}
                </small>
              ) : null}
            </label>

            {mode === 'register' ? (
              <label>
                <span>{t('auth.displayNameOptional')}</span>
                <input
                  autoComplete="name"
                  name="displayName"
                  placeholder={t('auth.displayNamePlaceholder')}
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                />
              </label>
            ) : null}

            <label>
              <span>{t('auth.password')}</span>
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
              {mode === 'register' ? (
                <small className={`auth-rule-item ${passwordLengthOk ? 'met' : ''}`}>
                  {passwordLengthOk ? <Check size={13} /> : <Circle size={13} />}
                  {t('auth.ruleMinChars')}
                </small>
              ) : null}
            </label>

            {mode === 'register' ? (
              <label>
                <span>{t('auth.confirmPassword')}</span>
                <div className="password-field">
                  <input
                    required
                    autoComplete="new-password"
                    minLength={8}
                    name="confirmPassword"
                    type={confirmVisible ? 'text' : 'password'}
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    onBlur={() => setConfirmTouched(true)}
                  />
                  <button
                    type="button"
                    onClick={() => setConfirmVisible((visible) => !visible)}
                    aria-label={confirmVisible ? t('auth.hidePassword') : t('auth.showPassword')}
                  >
                    {confirmVisible ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
                {showMismatch ? (
                  <small className="auth-rule-item error">
                    <XCircle size={13} />
                    {t('auth.rulePasswordMismatch')}
                  </small>
                ) : passwordsMatch ? (
                  <small className="auth-rule-item met">
                    <Check size={13} />
                    {t('auth.rulePasswordMatch')}
                  </small>
                ) : null}
              </label>
            ) : null}

            {error ? <div className="inline-error" role="alert">{error}</div> : null}

            <button className="primary-button auth-submit" type="submit" disabled={submitting}>
              <Dumbbell size={18} />
              <span>{submitLabel}</span>
              <ArrowRight size={18} />
            </button>
          </form>

          <footer className="auth-trust-footer">
            <Lock size={14} />
            <span>{t('auth.localOnlyBadge')}</span>
          </footer>
        </section>
      </div>
    </main>
  )
}
