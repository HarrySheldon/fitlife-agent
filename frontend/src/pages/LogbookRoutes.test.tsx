import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import { api } from '../services/api'
import { Logbook, LogbookImport } from './Logbook'
import { LogbookDay } from './logbook/LogbookDay'

vi.mock('../hooks/usePreferences', () => ({
  usePreferences: () => ({
    preferences: { language: 'en-US', unit_system: 'metric', timezone: 'UTC' },
    localDate: () => '2026-08-25',
  }),
}))

vi.mock('../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/api')>()
  return { ...original, api: { ...original.api, calendarDays: vi.fn(), calendarDay: vi.fn(), upload: vi.fn() } }
})

const day = {
  date: '2026-08-24', calories: 1800, protein: 120, carbs: 200, fat: 60,
  meal_count: 2, training_sessions: 1, training_duration_min: 45, has_data: true,
}

beforeEach(async () => {
  vi.clearAllMocks()
  await i18n.changeLanguage('en-US')
  vi.mocked(api.calendarDays).mockResolvedValue([day])
  vi.mocked(api.calendarDay).mockResolvedValue({ summary: day, meals: [], workouts: [] })
})

function renderRoute(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/logbook" element={<Logbook />} />
        <Route path="/logbook/import" element={<LogbookImport />} />
        <Route path="/logbook/:date" element={<LogbookDay />} />
      </Routes>
    </MemoryRouter>,
  )
}

function renderNavigableDay(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><Link to="/logbook/2026-08-25">Next day</Link><Routes><Route path="/logbook/:date" element={<LogbookDay />} /><Route path="/logbook" element={<h1>Logbook overview</h1>} /></Routes></MemoryRouter>)
}

describe('logbook task routes', () => {
  it('keeps the overview focused on browsing and links calendar dates to stable URLs', async () => {
    renderRoute('/logbook')
    const dateLink = await screen.findByRole('link', { name: /08-24/ })
    expect(dateLink).toHaveAttribute('href', '/logbook/2026-08-24')
    expect(api.calendarDay).not.toHaveBeenCalled()
    expect(document.querySelector('form')).not.toBeInTheDocument()
    expect(document.querySelector('input[type="file"]')).not.toBeInTheDocument()
  })

  it('owns date detail and points actions at the dedicated entry routes', async () => {
    renderRoute('/logbook/2026-08-24')
    await waitFor(() => expect(api.calendarDay).toHaveBeenCalledWith('2026-08-24'))
    expect(screen.getByRole('link', { name: /add meal/i })).toHaveAttribute('href', '/today/meal/new?date=2026-08-24')
    expect(screen.getByRole('link', { name: /add training/i })).toHaveAttribute('href', '/today/workout/new?date=2026-08-24')
    expect(screen.getByRole('link', { name: /smart entry/i })).toHaveAttribute('href', '/today/smart-entry?date=2026-08-24')
  })

  it('places CSV upload in its own import task route', () => {
    renderRoute('/logbook/import')
    expect(screen.getByText('CSV import')).toBeInTheDocument()
    expect(screen.getAllByLabelText(/csv/i)).toHaveLength(2)
  })

  it.each(['/logbook/not-a-date', '/logbook/2026-02-31', '/logbook/0000-01-01'])('rejects invalid date %s before requesting detail', async (path) => {
    renderRoute(path)
    expect(await screen.findByRole('heading', { name: 'Logbook' })).toBeInTheDocument()
    expect(api.calendarDay).not.toHaveBeenCalled()
  })

  it('clears failed date state while navigating to and rendering another date', async () => {
    vi.mocked(api.calendarDay)
      .mockRejectedValueOnce(new Error('Could not load first date'))
      .mockResolvedValueOnce({ summary: { ...day, date: '2026-08-25' }, meals: [{ date: '2026-08-25', meal: 'lunch', food: 'Rice', amount: '1 bowl', calories: 300, protein: 6, carbs: 65, fat: 1 }], workouts: [] })
    renderNavigableDay('/logbook/2026-08-24')
    expect(await screen.findByText('Could not load first date')).toBeInTheDocument()
    screen.getByRole('link', { name: 'Next day' }).click()
    expect(await screen.findByText('Rice')).toBeInTheDocument()
    expect(screen.queryByText('Could not load first date')).not.toBeInTheDocument()
  })

  it('does not show the previous date detail while the next date loads', async () => {
    let resolveNext!: (value: Awaited<ReturnType<typeof api.calendarDay>>) => void
    vi.mocked(api.calendarDay)
      .mockResolvedValueOnce({ summary: day, meals: [{ date: day.date, meal: 'lunch', food: 'Old rice', amount: '1 bowl', calories: 300, protein: 6, carbs: 65, fat: 1 }], workouts: [] })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveNext = resolve }))
    renderNavigableDay('/logbook/2026-08-24')
    expect(await screen.findByText('Old rice')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('link', { name: 'Next day' }))
    expect(screen.queryByText('Old rice')).not.toBeInTheDocument()
    expect(screen.getByText(/Loading logbook/)).toBeInTheDocument()
    resolveNext({ summary: { ...day, date: '2026-08-25' }, meals: [], workouts: [] })
    await waitFor(() => expect(screen.queryByText(/Loading logbook/)).not.toBeInTheDocument())
  })
})
