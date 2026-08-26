import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../../i18n'
import { api } from '../../services/api'
import { Review } from '../Review'
import { WeeklyReview } from './WeeklyReview'

vi.mock('../../hooks/useDashboard', () => ({
  useDashboard: () => ({
    data: {
      calorie_trend: [], protein_trend: [], workout_count_trend: [], macro_distribution: [],
    },
    loading: false,
    error: null,
  }),
}))

vi.mock('../../components/ChartCard', () => ({
  ChartCard: ({ title }: { title: string }) => <div>{title}</div>,
}))

vi.mock('../../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../services/api')>()
  return {
    ...original,
    api: {
      ...original.api,
      listWeeklyReports: vi.fn(),
      getWeeklyReport: vi.fn(),
      generateWeeklyReport: vi.fn(),
      interpretWeeklyReport: vi.fn(),
    },
  }
})

const storedReport = {
  week: '2026-W35',
  generated_at: '2026-08-26T10:00:00Z',
  report: {
    title: 'Week 35 report',
    sections: [{ title: 'Nutrition', content: 'Protein was steady.' }],
    checklist: ['Plan breakfast'],
    trace: {},
  },
}

beforeEach(async () => {
  vi.clearAllMocks()
  await i18n.changeLanguage('en-US')
  vi.mocked(api.listWeeklyReports).mockResolvedValue([storedReport])
  vi.mocked(api.getWeeklyReport).mockResolvedValue(storedReport)
  vi.mocked(api.generateWeeklyReport).mockResolvedValue(storedReport)
  vi.mocked(api.interpretWeeklyReport).mockResolvedValue({
    surface: 'review', action: 'explain_weekly_report', answer_markdown: 'Agent interpretation',
    intent: 'weekly', trace: {}, sources: [], model: 'configured-model', request_id: 'request-1',
  })
})

function renderRoute(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/review" element={<Review />} />
        <Route path="/review/week/:week" element={<WeeklyReview />} />
      </Routes>
    </MemoryRouter>,
  )
}

function renderNavigableWeek(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Link to="/review/week/2026-W35">Next week</Link>
      <Routes><Route path="/review/week/:week" element={<WeeklyReview />} /></Routes>
    </MemoryRouter>,
  )
}

describe('review task routes', () => {
  it('keeps the overview trend-only and links persisted report history', async () => {
    renderRoute('/review')

    expect(await screen.findByRole('link', { name: /2026-W35/ })).toHaveAttribute('href', '/review/week/2026-W35')
    expect(screen.getByText('Calorie trend')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /generate weekly report/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /explain weekly patterns/i })).not.toBeInTheDocument()
  })

  it('loads week detail and keeps generation and Agent interpretation explicit', async () => {
    renderRoute('/review/week/2026-W35')

    expect(await screen.findByRole('heading', { name: 'Week 35 report' })).toBeInTheDocument()
    expect(api.getWeeklyReport).toHaveBeenCalledWith('2026-W35')

    fireEvent.click(screen.getByRole('button', { name: /generate weekly report/i }))
    await waitFor(() => expect(api.generateWeeklyReport).toHaveBeenCalledWith('2026-W35'))

    fireEvent.click(screen.getByRole('button', { name: /explain weekly patterns/i }))
    await waitFor(() => expect(api.interpretWeeklyReport).toHaveBeenCalledWith('2026-W35'))
    expect(await screen.findByText('Agent interpretation')).toBeInTheDocument()
  })

  it('rejects an invalid week route before requesting detail', async () => {
    renderRoute('/review/week/2021-W53')

    expect(await screen.findByText(/valid ISO week/i)).toBeInTheDocument()
    expect(api.getWeeklyReport).not.toHaveBeenCalled()
  })

  it('does not let generation for the previous route replace the current week', async () => {
    const week34 = { ...storedReport, week: '2026-W34', report: { ...storedReport.report, title: 'Week 34 report' } }
    const week35 = { ...storedReport, report: { ...storedReport.report, title: 'Week 35 current' } }
    let resolveOldGeneration!: (value: typeof week34) => void
    vi.mocked(api.getWeeklyReport).mockImplementation(async (week) => week === '2026-W34' ? week34 : week35)
    vi.mocked(api.generateWeeklyReport).mockImplementationOnce(() => new Promise((resolve) => { resolveOldGeneration = resolve }))

    renderNavigableWeek('/review/week/2026-W34')
    expect(await screen.findByRole('heading', { name: 'Week 34 report' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /generate weekly report/i }))
    fireEvent.click(screen.getByRole('link', { name: 'Next week' }))
    expect(await screen.findByRole('heading', { name: 'Week 35 current' })).toBeInTheDocument()

    await act(async () => resolveOldGeneration({ ...week34, report: { ...week34.report, title: 'Stale generated week 34' } }))
    expect(screen.queryByRole('heading', { name: 'Stale generated week 34' })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Week 35 current' })).toBeInTheDocument()
  })

  it('does not show Agent interpretation returned for the previous route', async () => {
    const week34 = { ...storedReport, week: '2026-W34', report: { ...storedReport.report, title: 'Week 34 report' } }
    const week35 = { ...storedReport, report: { ...storedReport.report, title: 'Week 35 current' } }
    let resolveOldInterpretation!: (value: Awaited<ReturnType<typeof api.interpretWeeklyReport>>) => void
    vi.mocked(api.getWeeklyReport).mockImplementation(async (week) => week === '2026-W34' ? week34 : week35)
    vi.mocked(api.interpretWeeklyReport).mockImplementationOnce(() => new Promise((resolve) => { resolveOldInterpretation = resolve }))

    renderNavigableWeek('/review/week/2026-W34')
    expect(await screen.findByRole('heading', { name: 'Week 34 report' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /explain weekly patterns/i }))
    fireEvent.click(screen.getByRole('link', { name: 'Next week' }))
    expect(await screen.findByRole('heading', { name: 'Week 35 current' })).toBeInTheDocument()

    await act(async () => resolveOldInterpretation({
      surface: 'review', action: 'explain_weekly_report', answer_markdown: 'Stale week 34 interpretation',
      intent: 'weekly', trace: {}, sources: [], model: 'configured-model', request_id: 'stale-request',
    }))
    expect(screen.queryByText('Stale week 34 interpretation')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Week 35 current' })).toBeInTheDocument()
  })

  it('does not let a late same-week GET replace a newly generated report', async () => {
    const oldReport = { ...storedReport, report: { ...storedReport.report, title: 'Old GET report' } }
    const generatedReport = { ...storedReport, report: { ...storedReport.report, title: 'New generated report' } }
    let resolveGet!: (value: typeof oldReport) => void
    vi.mocked(api.getWeeklyReport).mockImplementationOnce(() => new Promise((resolve) => { resolveGet = resolve }))
    vi.mocked(api.generateWeeklyReport).mockResolvedValueOnce(generatedReport)

    renderRoute('/review/week/2026-W35')
    fireEvent.click(screen.getByRole('button', { name: /generate weekly report/i }))
    expect(await screen.findByRole('heading', { name: 'New generated report' })).toBeInTheDocument()

    await act(async () => resolveGet(oldReport))
    expect(screen.queryByRole('heading', { name: 'Old GET report' })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'New generated report' })).toBeInTheDocument()
  })

  it('prevents generation from crossing an in-flight interpretation for the same report', async () => {
    let resolveInterpretation!: (value: Awaited<ReturnType<typeof api.interpretWeeklyReport>>) => void
    vi.mocked(api.interpretWeeklyReport).mockImplementationOnce(() => new Promise((resolve) => { resolveInterpretation = resolve }))

    renderRoute('/review/week/2026-W35')
    expect(await screen.findByRole('heading', { name: 'Week 35 report' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /explain weekly patterns/i }))

    const generate = screen.getByRole('button', { name: /generate weekly report/i })
    expect(generate).toBeDisabled()
    fireEvent.click(generate)
    expect(api.generateWeeklyReport).not.toHaveBeenCalled()

    await act(async () => resolveInterpretation({
      surface: 'review', action: 'explain_weekly_report', answer_markdown: 'Current report interpretation',
      intent: 'weekly', trace: {}, sources: [], model: 'configured-model', request_id: 'current-request',
    }))
    expect(screen.getByText('Current report interpretation')).toBeInTheDocument()
  })
})
