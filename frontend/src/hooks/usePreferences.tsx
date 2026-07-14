import type { ReactNode } from 'react'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import i18n from '../i18n'
import { api, browserTimezone, languageStorage } from '../services/api'
import type { AppLanguage, UserPreferences, UserPreferencesUpdate } from '../types'
import { useAuth } from './useAuth'


interface PreferencesContextValue {
  preferences: UserPreferences
  loading: boolean
  error: string | null
  updatePreferences: (update: UserPreferencesUpdate) => Promise<void>
  localDate: (date?: Date) => string
}

const PreferencesContext = createContext<PreferencesContextValue | null>(null)

function initialPreferences(): UserPreferences {
  return {
    language: languageStorage.get(),
    unit_system: 'metric',
    timezone: browserTimezone(),
  }
}

function applyLanguage(language: AppLanguage) {
  languageStorage.set(language)
  document.documentElement.lang = language
  void i18n.changeLanguage(language)
}

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [preferences, setPreferences] = useState<UserPreferences>(initialPreferences)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    applyLanguage(preferences.language)
  }, [preferences.language])

  useEffect(() => {
    if (!user) {
      setPreferences(initialPreferences())
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    api.preferences()
      .then((stored) => {
        if (!cancelled) setPreferences(stored)
      })
      .catch((cause: Error) => {
        if (!cancelled) setError(cause.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [user])

  const updatePreferences = useCallback(async (update: UserPreferencesUpdate) => {
    const previous = preferences
    const optimistic = { ...preferences, ...update }
    setPreferences(optimistic)
    setError(null)
    try {
      setPreferences(await api.updatePreferences(update))
    } catch (cause) {
      setPreferences(previous)
      setError((cause as Error).message)
      throw cause
    }
  }, [preferences])

  const localDate = useCallback((value = new Date()) => {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: preferences.timezone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(value)
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
    return `${values.year}-${values.month}-${values.day}`
  }, [preferences.timezone])

  const context = useMemo(
    () => ({ preferences, loading, error, updatePreferences, localDate }),
    [preferences, loading, error, updatePreferences, localDate],
  )

  return <PreferencesContext.Provider value={context}>{children}</PreferencesContext.Provider>
}

export function usePreferences() {
  const value = useContext(PreferencesContext)
  if (!value) throw new Error('usePreferences must be used within PreferencesProvider')
  return value
}

