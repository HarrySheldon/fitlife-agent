import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api } from '../services/api'
import type { ModelConnectionSettings, ModelConnectionTestResult, ModelSettingsUpdate } from '../types'

type ModelAction = 'save' | 'clear' | 'list' | 'test' | null

interface Feedback {
  kind: 'success' | 'error'
  message: string
}

export function useModelSettings() {
  const { t } = useTranslation()
  const errorMessage = useCallback(
    (error: unknown) => error instanceof Error ? error.message : t('settingsModel.requestFailed'),
    [t],
  )
  const [settings, setSettings] = useState<ModelConnectionSettings | null>(null)
  const [models, setModels] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [action, setAction] = useState<ModelAction>(null)
  const [feedback, setFeedback] = useState<Feedback | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setSettings(await api.modelSettings())
      setFeedback(null)
    } catch (error) {
      setFeedback({ kind: 'error', message: errorMessage(error) })
    } finally {
      setLoading(false)
    }
  }, [errorMessage])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const save = useCallback(async (update: ModelSettingsUpdate) => {
    setAction('save')
    setFeedback(null)
    try {
      const saved = await api.saveModelSettings(update)
      setSettings(saved)
      setFeedback({ kind: 'success', message: t('settingsModel.saved') })
      return saved
    } catch (error) {
      setFeedback({ kind: 'error', message: errorMessage(error) })
      return null
    } finally {
      setAction(null)
    }
  }, [errorMessage, t])

  const clearApiKey = useCallback(async () => {
    setAction('clear')
    setFeedback(null)
    try {
      const saved = await api.clearModelApiKey()
      setSettings(saved)
      setModels([])
      setFeedback({ kind: 'success', message: t('settingsModel.keyCleared') })
      return true
    } catch (error) {
      setFeedback({ kind: 'error', message: errorMessage(error) })
      return false
    } finally {
      setAction(null)
    }
  }, [errorMessage, t])

  const listModels = useCallback(async () => {
    setAction('list')
    setFeedback(null)
    try {
      const result = await api.listModels()
      setModels(result.models)
      setFeedback({ kind: 'success', message: t('settingsModel.modelsLoaded', { count: result.models.length }) })
    } catch (error) {
      setFeedback({ kind: 'error', message: errorMessage(error) })
    } finally {
      setAction(null)
    }
  }, [errorMessage, t])

  const testConnection = useCallback(async (): Promise<ModelConnectionTestResult | null> => {
    setAction('test')
    setFeedback(null)
    try {
      const result = await api.testModelConnection()
      setSettings(await api.modelSettings())
      setFeedback({ kind: 'success', message: t('settingsModel.connectionPassed', { latency: result.latency_ms }) })
      return result
    } catch (error) {
      setFeedback({ kind: 'error', message: errorMessage(error) })
      try {
        setSettings(await api.modelSettings())
      } catch {
        // Keep the original test error visible.
      }
      return null
    } finally {
      setAction(null)
    }
  }, [errorMessage, t])

  return {
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
  }
}
