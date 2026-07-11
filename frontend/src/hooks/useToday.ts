import { useCallback, useEffect, useState } from 'react'

import { api } from '../services/api'
import type { TodayOverview } from '../types'

export function useToday(date: string) {
  const [data, setData] = useState<TodayOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await api.today(date))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }, [date])

  useEffect(() => {
    void refresh()
  }, [refresh])

  return { data, loading, error, refresh }
}
