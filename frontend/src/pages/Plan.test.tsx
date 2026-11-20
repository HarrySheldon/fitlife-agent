import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import { api } from '../services/api'
import { planCycleApi, type ActivePlanCycleResponse } from '../services/planCycleApi'
import { Plan } from './Plan'

vi.mock('../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/api')>()
  return {
    ...original,
    api: {
      ...original.api,
      listPlans: vi.fn(),
    },
  }
})

vi.mock('../services/planCycleApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/planCycleApi')>()
  return {
    ...original,
    planCycleApi: {
      ...original.planCycleApi,
      getActiveCycle: vi.fn(),
      activateCycle: vi.fn(),
      discardDraft: vi.fn(),
      updateDay: vi.fn(),
      prefillWorkoutFromDay: vi.fn(),
    },
  }
})

const sampleCycle: ActivePlanCycleResponse = {
  active: {
    id: 'cycle-1',
    title: '8-Week Fat Loss Block',
    goal_type: 'fat_loss',
    start_date: '2026-11-16',
    duration_weeks: 8,
    phases: [
      { name: 'Base Phase', start_week: 1, end_week: 2, focus: 'technique_base', volume_multiplier: 0.85 },
    ],
    status: 'active',
    source: 'deterministic',
    rationale: {},
    version: 1,
    created_at: '2026-11-16T00:00:00Z',
    updated_at: '2026-11-16T00:00:00Z',
    activated_at: '2026-11-16T00:00:00Z',
  },
  current_week: 1,
  adherence: { completed: 2, planned: 4, missed: 0, skipped: 0, pct: 50 },
  days: [
    {
      id: 'pday-1',
      cycle_id: 'cycle-1',
      week_index: 1,
      day_of_week: 1,
      scheduled_date: '2026-11-16',
      day_type: 'training',
      focus: 'Lower Body Strength',
      estimated_duration_min: 50,
      prescribed_exercises: [
        {
          catalog_exercise_id: 'ex-squat',
          name: 'Barbell Squat',
          primary_muscle: 'quads',
          exercise_type: 'strength',
          sets: 4,
          reps: 8,
          target_weight_kg: 65,
          duration_min: null,
          rest_sec: 90,
          notes: '',
        },
      ],
      nutrition_override: {},
      status_override: null,
      notes: 'Focus on depth',
      adherence: 'completed',
      logged_session_count: 1,
    },
  ],
  drafts: [
    {
      id: 'cycle-draft-1',
      title: 'Next Week Auto Draft',
      goal_type: 'fat_loss',
      start_date: '2026-11-23',
      duration_weeks: 4,
      phases: [],
      status: 'draft',
      source: 'weekly_auto',
      rationale: { warnings: ['Keep at least 1 rest day.'] },
      version: 1,
      created_at: '2026-11-20T00:00:00Z',
      updated_at: '2026-11-20T00:00:00Z',
      activated_at: null,
      week1_days: [],
    },
  ],
  history: [],
}

beforeEach(async () => {
  vi.clearAllMocks()
  vi.mocked(api.listPlans).mockResolvedValue([])
  vi.mocked(planCycleApi.getActiveCycle).mockResolvedValue(sampleCycle)
  vi.mocked(planCycleApi.activateCycle).mockResolvedValue({ cycle: sampleCycle.active! })
  await i18n.changeLanguage('en-US')
})

describe('Plan periodized cycle workspace', () => {
  it('renders active cycle, adherence, day exercises, and pending draft confirmation', async () => {
    render(
      <MemoryRouter>
        <Plan />
      </MemoryRouter>,
    )
    expect(await screen.findByText('8-Week Fat Loss Block')).toBeInTheDocument()
    expect(screen.getByText('2/4 (50%)')).toBeInTheDocument()
    expect(screen.getByText('Barbell Squat')).toBeInTheDocument()
    expect(screen.getByText('4 × 8 @ 65 kg')).toBeInTheDocument()
    expect(screen.getByText('Next Week Auto Draft')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Confirm & activate/ }))
    await waitFor(() => {
      expect(planCycleApi.activateCycle).toHaveBeenCalledWith('cycle-draft-1')
    })
  })
})
