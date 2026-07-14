import { useCallback, useEffect, useState } from 'react'

import { api } from '../services/api'
import type { ModelConnectionSettings, ModelConnectionTestResult, ModelSettingsUpdate } from '../types'

type ModelAction = 'save' | 'clear' | 'list' | 'test' | null

interface Feedback {
  kind: 'success' | 'error'
  message: string
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'The request could not be completed.'
}

export function useModelSettings() {
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
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const save = useCallback(async (update: ModelSettingsUpdate) => {
    setAction('save')
    setFeedback(null)
    try {
      const saved = await api.saveModelSettings(update)
      setSettings(saved)
      setFeedback({ kind: 'success', message: 'Model settings saved.' })
      return saved
    } catch (error) {
      setFeedback({ kind: 'error', message: errorMessage(error) })
      return null
    } finally {
      setAction(null)
    }
  }, [])

  const clearApiKey = useCallback(async () => {
    setAction('clear')
    setFeedback(null)
    try {
      const saved = await api.clearModelApiKey()
      setSettings(saved)
      setModels([])
      setFeedback({ kind: 'success', message: 'API key cleared.' })
      return true
    } catch (error) {
      setFeedback({ kind: 'error', message: errorMessage(error) })
      return false
    } finally {
      setAction(null)
    }
  }, [])

  const listModels = useCallback(async () => {
    setAction('list')
    setFeedback(null)
    try {
      const result = await api.listModels()
      setModels(result.models)
      setFeedback({ kind: 'success', message: `${result.models.length} models loaded.` })
    } catch (error) {
      setFeedback({ kind: 'error', message: errorMessage(error) })
    } finally {
      setAction(null)
    }
  }, [])

  const testConnection = useCallback(async (): Promise<ModelConnectionTestResult | null> => {
    setAction('test')
    setFeedback(null)
    try {
      const result = await api.testModelConnection()
      setSettings(await api.modelSettings())
      setFeedback({ kind: 'success', message: `Connection passed in ${result.latency_ms} ms.` })
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
  }, [])

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
