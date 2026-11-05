import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { api } from '../services/api'
import type { TodayOverview } from '../types'
import { Today } from './Today'

const coach = vi.hoisted(() => ({ send: vi.fn() }))
vi.mock('../services/api', () => ({ api: { today: vi.fn() } }))
vi.mock('../hooks/usePreferences', () => ({ usePreferences: () => ({ localDate: () => '2026-11-04' }) }))
vi.mock('../hooks/useCoach', () => ({ useCoach: () => ({ sending: false, active: null, send: coach.send }) }))
vi.mock('../components/CoachDrawer', () => ({ CoachDrawer: () => null }))

function pending() {
  let resolve!: (value: TodayOverview) => void
  let reject!: (error: Error) => void
  const promise = new Promise<TodayOverview>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function overview(date: string): TodayOverview {
  return { date, target: null, consumed: { calories: 0, carbs: 0, protein: 0, fat: 0 },
    planned_meal_count: 0, recorded_meal_count: 1, coach_actions: ['explain_today'],
    meals: [{ id: 'meal', name: `Meal ${date}`, meal_type: 'lunch', position: 1, item_count: 1,
      nutrition: { calories: 0, carbs: 0, protein: 0, fat: 0 } }] }
}
beforeEach(async () => {
  vi.mocked(api.today).mockReset()
  coach.send.mockReset()
  await i18n.changeLanguage('en-US')
})

it('shows loading for the new date and never restores old meals after a failure', async () => {
  const first = pending(), second = pending()
  vi.mocked(api.today).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
  render(<MemoryRouter><Today /></MemoryRouter>)
  await act(async () => first.resolve(overview('2026-11-04')))
  expect(screen.getByText('Meal 2026-11-04')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Date'), { target: { value: '2026-11-05' } })
  expect(screen.queryByText('Meal 2026-11-04')).not.toBeInTheDocument()
  expect(screen.getByText(/Loading today/)).toBeInTheDocument()
  await act(async () => second.reject(new Error('Network unavailable')))
  expect(screen.getByText('Network unavailable')).toBeInTheDocument()
  expect(screen.queryByText('Meal 2026-11-04')).not.toBeInTheDocument()
})

it('keeps the displayed records and the coach action on the selected date after reverse responses', async () => {
  const first = pending(), second = pending()
  vi.mocked(api.today).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
  render(<MemoryRouter><Today /></MemoryRouter>)
  fireEvent.change(screen.getByLabelText('Date'), { target: { value: '2026-11-05' } })
  await act(async () => second.resolve(overview('2026-11-05')))
  await act(async () => first.resolve(overview('2026-11-04')))
  expect(screen.getByText('Meal 2026-11-05')).toBeInTheDocument()
  expect(screen.queryByText('Meal 2026-11-04')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: i18n.t('today.explain') }))
  expect(coach.send).toHaveBeenCalledWith(expect.objectContaining({ date: '2026-11-05', surface: 'today' }))
})
