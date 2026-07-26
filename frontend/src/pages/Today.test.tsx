import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import type { TodayOverview } from '../types'
import { Today } from './Today'

const state = vi.hoisted(() => ({
  data: null as TodayOverview | null,
  refresh: vi.fn(),
  setPlannedMealCount: vi.fn(),
}))

vi.mock('../hooks/usePreferences', () => ({
  usePreferences: () => ({ localDate: () => '2026-07-25' }),
}))

vi.mock('../hooks/useToday', () => ({
  useToday: () => ({
    data: state.data,
    loading: false,
    error: null,
    refresh: state.refresh,
  }),
}))

vi.mock('../services/api', () => ({
  api: {
    setPlannedMealCount: state.setPlannedMealCount,
  },
}))

vi.mock('../components/CoachPanel', () => ({
  CoachPanel: () => <aside aria-label="Coach panel" />,
}))

const base: TodayOverview = {
  date: '2026-07-25',
  target: {
    id: 'target-1',
    source: 'manual',
    effective_from: '2026-07-01T00:00:00Z',
    calories: 2200,
    carbs: 260,
    protein: 130,
    fat: 70,
  },
  consumed: {
    calories: 690,
    carbs: 82,
    protein: 42,
    fat: 19,
  },
  planned_meal_count: 3,
  recorded_meal_count: 1,
  coach_actions: [],
}

beforeEach(async () => {
  state.data = base
  state.refresh.mockReset().mockResolvedValue(undefined)
  state.setPlannedMealCount.mockReset().mockResolvedValue(base)
  await i18n.changeLanguage('en-US')
})

describe('Today SQLite daily summary', () => {
  it('renders four nutrition metrics and confirmed meal and workout summaries', () => {
    state.data = {
      ...base,
      meals: [{
        id: 'meal-1',
        name: 'Lunch',
        meal_type: 'lunch',
        position: 1,
        item_count: 2,
        nutrition: { calories: 690, carbs: 82, protein: 42, fat: 19 },
      }],
      workouts: [{
        id: 'workout-1',
        title: 'Lower body',
        started_at: null,
        duration_min: 50,
        intensity: 'medium',
        calories: 210,
        contains_estimates: true,
        strength_exercise_count: 2,
        strength_set_count: 7,
        cardio_item_count: 0,
      }],
    }
    render(<MemoryRouter><Today /></MemoryRouter>)

    for (const name of ['Calories', 'Carbohydrate', 'Protein', 'Fat']) {
      expect(screen.getByText(name)).toBeInTheDocument()
    }
    expect(screen.getByText('1 of 3 meals')).toBeInTheDocument()
    expect(screen.getByText('Lunch', { selector: 'strong' })).toBeInTheDocument()
    expect(screen.getByText('Lower body')).toBeInTheDocument()
    expect(screen.getByText(/210 kcal/)).toBeInTheDocument()
    expect(screen.getByText(/contains estimates/)).toBeInTheDocument()
  })

  it('hides meal and training sections when the backend omits them', () => {
    render(<MemoryRouter><Today /></MemoryRouter>)

    expect(screen.queryByRole('heading', { name: 'Meals' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Training' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add meal' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add training' })).toBeInTheDocument()
  })

  it('updates the selected day planned meal count through its own endpoint', async () => {
    render(<MemoryRouter><Today /></MemoryRouter>)

    fireEvent.change(screen.getByLabelText('Planned meals'), {
      target: { value: '5' },
    })

    await waitFor(() => expect(state.setPlannedMealCount).toHaveBeenCalledWith(
      '2026-07-25',
      5,
    ))
    expect(state.refresh).toHaveBeenCalledOnce()
  })
})
