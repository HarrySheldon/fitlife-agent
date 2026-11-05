import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '../services/api'
import type { TodayOverview } from '../types'
import { useToday } from './useToday'

vi.mock('../services/api', () => ({ api: { today: vi.fn() } }))

function pending() {
  let resolve!: (value: TodayOverview) => void
  let reject!: (error: Error) => void
  const promise = new Promise<TodayOverview>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

function overview(date: string): TodayOverview {
  return { date, target: null, consumed: { calories: 0, carbs: 0, protein: 0, fat: 0 },
    planned_meal_count: 0, recorded_meal_count: 0, coach_actions: [] }
}

beforeEach(() => vi.mocked(api.today).mockReset())

it('never lets an older date response overwrite the selected date', async () => {
  const first = pending(), second = pending()
  vi.mocked(api.today).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
  const { result, rerender } = renderHook(({ date }) => useToday(date), { initialProps: { date: '2026-11-04' } })
  rerender({ date: '2026-11-05' })
  await act(async () => second.resolve(overview('2026-11-05')))
  await act(async () => first.resolve(overview('2026-11-04')))
  expect(result.current.data?.date).toBe('2026-11-05')
})

it('hides old data immediately on a date change and does not restore it on failure', async () => {
  const first = pending(), second = pending()
  vi.mocked(api.today).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
  const { result, rerender } = renderHook(({ date }) => useToday(date), { initialProps: { date: '2026-11-04' } })
  await act(async () => first.resolve(overview('2026-11-04')))
  rerender({ date: '2026-11-05' })
  expect(result.current.data).toBeNull()
  expect(result.current.loading).toBe(true)
  await act(async () => second.reject(new Error('Unavailable')))
  expect(result.current.data).toBeNull()
  expect(result.current.error).toBe('Unavailable')
})

it('does not let a stale failure clear loading or show an error for a newer request', async () => {
  const first = pending(), second = pending()
  vi.mocked(api.today).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
  const { result, rerender } = renderHook(({ date }) => useToday(date), { initialProps: { date: '2026-11-04' } })
  rerender({ date: '2026-11-05' })
  await act(async () => first.reject(new Error('Old failure')))
  expect(result.current.loading).toBe(true)
  expect(result.current.error).toBeNull()
  await act(async () => second.resolve(overview('2026-11-05')))
})

it('keeps same-day data during refresh and marks it stale if refresh fails', async () => {
  const first = pending(), second = pending()
  vi.mocked(api.today).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
  const { result } = renderHook(() => useToday('2026-11-05'))
  await act(async () => first.resolve(overview('2026-11-05')))
  let refresh!: Promise<void>
  act(() => { refresh = result.current.refresh() })
  expect(result.current.data?.date).toBe('2026-11-05')
  expect(result.current.refreshing).toBe(true)
  await act(async () => { second.reject(new Error('Offline')); await refresh })
  expect(result.current.stale).toBe(true)
  expect(result.current.loading).toBe(false)
})

it('accepts only the latest overlapping same-day refresh', async () => {
  const requests = [pending(), pending(), pending()]
  for (const request of requests) vi.mocked(api.today).mockReturnValueOnce(request.promise)
  const { result } = renderHook(() => useToday('2026-11-05'))
  await act(async () => requests[0].resolve(overview('2026-11-05')))
  act(() => { void result.current.refresh(); void result.current.refresh() })
  await act(async () => requests[2].resolve({ ...overview('2026-11-05'), recorded_meal_count: 2 }))
  await act(async () => requests[1].resolve({ ...overview('2026-11-05'), recorded_meal_count: 1 }))
  expect(result.current.data?.recorded_meal_count).toBe(2)
})

it('ignores the discarded StrictMode effect request', async () => {
  const first = pending(), second = pending()
  vi.mocked(api.today).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
  const { result } = renderHook(() => useToday('2026-11-05'), { reactStrictMode: true })
  expect(api.today).toHaveBeenCalledTimes(2)
  await act(async () => second.resolve({ ...overview('2026-11-05'), recorded_meal_count: 2 }))
  await act(async () => first.resolve({ ...overview('2026-11-05'), recorded_meal_count: 1 }))
  expect(result.current.data?.recorded_meal_count).toBe(2)
})

it('a retained callback cannot restart an old date or a disposed hook', async () => {
  const first = pending(), second = pending()
  vi.mocked(api.today).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
  const { result, rerender, unmount } = renderHook(({ date }) => useToday(date), { initialProps: { date: '2026-11-04' } })
  const oldRefresh = result.current.refresh
  rerender({ date: '2026-11-05' })
  await act(async () => oldRefresh())
  expect(api.today).toHaveBeenCalledTimes(2)
  const lastRefresh = result.current.refresh
  unmount()
  await act(async () => { await lastRefresh(); first.resolve(overview('2026-11-04')); second.resolve(overview('2026-11-05')) })
  expect(api.today).toHaveBeenCalledTimes(2)
})
