import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../services/api'
import type { TodayOverview } from '../types'

export function useToday(date: string) {
  const [state, setState] = useState<{
    date: string; data: TodayOverview | null; loading: boolean; error: string | null
  }>({ date, data: null, loading: true, error: null })
  const requestVersion = useRef(0)
  const mounted = useRef(false)
  const activeDate = useRef(date)

  const refresh = useCallback(async () => {
    // A saved refresh callback from a previous date cannot supersede the current query.
    if (!mounted.current || activeDate.current !== date) return
    const version = ++requestVersion.current
    setState(previous => ({ date, data: previous.date === date ? previous.data : null,
      loading: true, error: null }))
    try {
      const data = await api.today(date)
      if (mounted.current && version === requestVersion.current) {
        setState({ date, data, loading: false, error: null })
      }
    } catch (err) {
      if (mounted.current && version === requestVersion.current) {
        setState(previous => ({ ...previous, loading: false,
          error: err instanceof Error ? err.message : String(err) }))
      }
    }
  }, [date])

  useEffect(() => {
    mounted.current = true
    activeDate.current = date
    void refresh()
    return () => {
      mounted.current = false
      requestVersion.current += 1
    }
  }, [date, refresh])

  // Hide the old query even in the render before the new effect starts.
  const current = state.date === date ? state : { data: null, loading: true, error: null }
  return { ...current, refresh, refreshing: current.loading && current.data !== null,
    stale: current.error !== null && current.data !== null }
}
